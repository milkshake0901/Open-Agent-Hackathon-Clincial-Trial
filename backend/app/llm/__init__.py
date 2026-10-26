"""app/llm — LLM gateway. One function. Owns lanes, provider, structured parsing, model_answered logging.

Agents are LangChain agents: they take their model from `ctx.llm.chat_model(lane)` (Nightshift), so
the provider, headers and Nemotron lane pinning live here and nowhere else. Media generation on a
Meterless job is `Media` (app/llm/media.py)."""
from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Generic, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from app import logfile
from app.trace import RunId

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

T = TypeVar("T", bound=BaseModel)


class Lane(StrEnum):
    """Which Nightshift model serves each lane is configuration (config.py LANE_MODELS)."""
    FAST = "fast"      # Intake, criteria split
    DEEP = "deep"      # Matcher
    JUDGE = "judge"    # Evaluator support check


@dataclass(frozen=True)
class Reply:
    """What a provider answers: the reply text as the model sent it, unparsed, and the call's metadata."""
    text: str
    model_requested: str
    model_answered: str      # from the response's `model` field; logged on LlmCalled
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int


@dataclass(frozen=True)
class Completion(Generic[T]):
    value: T
    model_requested: str
    model_answered: str      # from the response's `model` field; logged on LlmCalled
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int


def strip_reasoning(text: str) -> str:
    """Some lanes leak their reasoning, sometimes without the opening tag: keep what follows the last </think>."""
    return text.rsplit("</think>", 1)[-1].strip()


def json_object(text: str) -> str:
    """The JSON object in a reply, without reasoning or code fences."""
    text = strip_reasoning(text)
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fenced:
        text = fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    return text[start : end + 1] if start != -1 and end > start else text


class LLM(Protocol):
    async def complete(self, lane: Lane, system: str, user: str, out: type[T]) -> Reply:
        """JSON-mode call; `out` is the shape the prompt asks for. app.llm.complete parses the reply."""
        ...
    def model_for(self, lane: Lane | None) -> str:
        """The model a lane asks for; the log file names it when a call fails before any reply."""
        ...
    def chat_model(self, lane: Lane | None = None) -> "BaseChatModel":
        """LangChain chat model on the lane's pinned model; agents are built on this."""
        ...


async def complete(ctx, lane: Lane, *, system: str, user: str, out: type[T], run_id: RunId | None) -> Completion[T]:
    """JSON-mode call, parse the reply into `out`; ONE transport-level retry on parse failure with the validation error
    appended (this is not a domain loop and is not traced as one). Records an llm_call row and emits LlmCalled to the run when run_id given.
    Timeout 180 s (model load). Raises LlmUnavailable after that; loops treat it as a failed Trial / Rejected run.
    Every attempt writes one `llm.complete` line to the log file (app.logfile), run or not."""
    from app import trace
    from app.trace.events import LlmCalled

    prompt = user
    for attempt in (1, 2):
        started = time.monotonic()
        try:
            reply = await asyncio.wait_for(ctx.llm.complete(lane, system, prompt, out), timeout=_TIMEOUT_S)
        except Exception as e:   # timeout, transport, provider: one place turns them into LlmUnavailable
            _log_call(ctx, lane, system, prompt, run_id, started, error=f"{type(e).__name__}: {e}")
            if run_id is not None:
                await trace.record_llm_call(ctx.writer, run_id, _failed(lane))
            raise LlmUnavailable(f"{lane} model unavailable: {e}") from e
        try:
            value = out.model_validate_json(json_object(reply.text))
        except ValidationError as invalid:
            _log_call(ctx, lane, system, prompt, run_id, started, raw=reply.text, error=str(invalid))
            if run_id is not None:
                await trace.record_llm_call(ctx.writer, run_id, _failed(lane))
            if attempt == 2:
                raise LlmUnavailable(f"{lane} lane reply did not parse twice: {invalid.error_count()} errors") from invalid
            prompt = (f"{user}\n\nYour previous answer did not match the schema:\n{invalid}\n"
                      "Answer again with valid JSON.")
            continue
        completion = Completion(value=value, model_requested=reply.model_requested,
                                model_answered=reply.model_answered, prompt_tokens=reply.prompt_tokens,
                                completion_tokens=reply.completion_tokens, latency_ms=reply.latency_ms)
        _log_call(ctx, lane, system, prompt, run_id, started, raw=reply.text, completion=completion)
        if run_id is not None:   # an llm_call row and an LlmCalled event belong to a run
            call_id = await trace.record_llm_call(ctx.writer, run_id, trace.LlmCall(
                id=_call_id(), lane=lane, model_requested=completion.model_requested,
                model_answered=completion.model_answered, latency_ms=completion.latency_ms,
                prompt_tokens=completion.prompt_tokens, completion_tokens=completion.completion_tokens, ok=True))
            await trace.append(ctx.writer, run_id, LlmCalled(actor="llm", llm_call_id=call_id, lane=lane,
                                                            model_answered=completion.model_answered),
                               llm_call_ids=(call_id,))
        return completion
    raise AssertionError("unreachable")


_TIMEOUT_S = 180
log = logging.getLogger(__name__)


def _log_call(ctx, lane: Lane, system: str, user: str, run_id: RunId | None, started: float, *,
              completion: Completion | None = None, raw: str | None = None, error: str | None = None) -> None:
    """The prompts are the de-identified text the model was sent; nothing else about the patient is added.
    `raw` is the reply text as the model sent it; None when no reply came."""
    logfile.step(log, "llm.complete", lane=str(lane),
                 model_requested=completion.model_requested if completion else ctx.llm.model_for(lane),
                 model_answered=completion.model_answered if completion else None, system=system, user=user,
                 raw=raw, parsed=completion.value.model_dump(mode="json") if completion else None, error=error,
                 duration_ms=int((time.monotonic() - started) * 1000), run_id=run_id)


def _call_id() -> str:
    return f"llm_{uuid.uuid4().hex}"


def _failed(lane: Lane):
    from app import trace
    return trace.LlmCall(id=_call_id(), lane=lane, model_requested="unknown", model_answered="none", latency_ms=0,
                         prompt_tokens=0, completion_tokens=0, ok=False)


class LlmUnavailable(Exception): ...


from app.llm.media import Media, MediaFailed, MediaKind, MediaUnavailable, Plan, StoredMedia  # noqa: E402
