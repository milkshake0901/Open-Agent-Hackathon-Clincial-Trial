"""app/llm — LLM gateway. One function. Owns lanes, provider, structured parsing, model_answered logging.

Agents are LangChain agents: they take their model from `ctx.llm.chat_model(lane)` (Nightshift), so
the provider, headers and Nemotron lane pinning live here and nowhere else. Media generation on a
Meterless job is `Media` (app/llm/media.py)."""
from __future__ import annotations

import asyncio
import logging
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
class Completion(Generic[T]):
    value: T
    model_requested: str
    model_answered: str      # from the response's `model` field; logged on LlmCalled
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int
    raw: str | None = None   # the reply text as the model sent it; written to the log file only


class UnparsedReply(Exception):
    """A provider's reply that did not validate against `out`: the ValidationError and the raw text, so the log
    file can show what the model said. app.llm.complete treats it as a pydantic.ValidationError."""
    def __init__(self, raw: str, error: ValidationError) -> None:
        super().__init__(str(error))
        self.raw, self.error = raw, error


class LLM(Protocol):
    async def complete(self, lane: Lane, system: str, user: str, out: type[T]) -> Completion[T]: ...
    def model_for(self, lane: Lane | None) -> str:
        """The model a lane asks for; the log file names it when a call fails before any reply."""
        ...
    def chat_model(self, lane: Lane | None = None) -> "BaseChatModel":
        """LangChain chat model on the lane's pinned model; agents are built on this."""
        ...


async def complete(ctx, lane: Lane, *, system: str, user: str, out: type[T], run_id: RunId | None) -> Completion[T]:
    """JSON-mode call, parse into `out`; ONE transport-level retry on parse failure with the validation error
    appended (this is not a domain loop and is not traced as one). Records an llm_call row and emits LlmCalled to the run when run_id given.
    Timeout 180 s (model load). Raises LlmUnavailable after that; loops treat it as a failed Trial / Rejected run.
    Every attempt writes one `llm.complete` line to the log file (app.logfile), run or not."""
    from app import trace
    from app.trace.events import LlmCalled

    prompt = user
    for attempt in (1, 2):
        started = time.monotonic()
        try:
            completion = await asyncio.wait_for(ctx.llm.complete(lane, system, prompt, out), timeout=_TIMEOUT_S)
        except (ValidationError, UnparsedReply) as e:
            raw, invalid = (e.raw, e.error) if isinstance(e, UnparsedReply) else (None, e)
            _log_call(ctx, lane, system, prompt, run_id, started, raw=raw, error=str(invalid))
            if run_id is not None:
                await trace.record_llm_call(ctx.writer, run_id, _failed(lane))
            if attempt == 2:
                raise LlmUnavailable(f"{lane} lane reply did not parse twice: {invalid.error_count()} errors") from invalid
            prompt = (f"{user}\n\nYour previous answer did not match the schema:\n{invalid}\n"
                      "Answer again with valid JSON.")
            continue
        except Exception as e:   # timeout, transport, provider: one place turns them into LlmUnavailable
            _log_call(ctx, lane, system, prompt, run_id, started, error=f"{type(e).__name__}: {e}")
            if run_id is not None:
                await trace.record_llm_call(ctx.writer, run_id, _failed(lane))
            raise LlmUnavailable(f"{lane} model unavailable: {e}") from e
        _log_call(ctx, lane, system, prompt, run_id, started, completion=completion)
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
    """The prompts are the de-identified text the model was sent; nothing else about the patient is added."""
    try:
        requested = completion.model_requested if completion else ctx.llm.model_for(lane)
        logfile.step(log, "llm.complete", lane=str(lane), model_requested=requested,
                     model_answered=completion.model_answered if completion else None, system=system, user=user,
                     raw=completion.raw if completion else raw,
                     parsed=completion.value.model_dump(mode="json") if completion else None, error=error,
                     duration_ms=int((time.monotonic() - started) * 1000), run_id=run_id)
    except Exception:   # noqa: BLE001 — the log never fails a model call
        pass


def _call_id() -> str:
    return f"llm_{uuid.uuid4().hex}"


def _failed(lane: Lane):
    from app import trace
    return trace.LlmCall(id=_call_id(), lane=lane, model_requested="unknown", model_answered="none", latency_ms=0,
                         prompt_tokens=0, completion_tokens=0, ok=False)


class LlmUnavailable(Exception): ...


from app.llm.media import Media, MediaFailed, MediaKind, MediaUnavailable, Plan, StoredMedia  # noqa: E402
