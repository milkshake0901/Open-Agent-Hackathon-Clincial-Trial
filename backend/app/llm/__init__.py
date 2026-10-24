"""app/llm — LLM gateway. One function. Owns lanes, provider, structured parsing, model_answered logging."""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Generic, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from app.trace import RunId

T = TypeVar("T", bound=BaseModel)


class Lane(StrEnum):
    """Which Nightshift model serves each lane is configuration, decided later (config.py LANE_MODELS)."""
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


class LLM(Protocol):
    async def complete(self, lane: Lane, system: str, user: str, out: type[T]) -> Completion[T]: ...


async def complete(ctx, lane: Lane, *, system: str, user: str, out: type[T], run_id: RunId | None) -> Completion[T]:
    """JSON-mode call, parse into `out`; ONE transport-level retry on parse failure with the validation error
    appended (this is not a domain loop and is not traced as one). Records an llm_call row and emits LlmCalled to the run when run_id given.
    Timeout 180 s (model load). Raises LlmUnavailable after that; loops treat it as a failed Trial / Rejected run."""
    from app import trace
    from app.trace.events import LlmCalled

    prompt = user
    for attempt in (1, 2):
        try:
            completion = await asyncio.wait_for(ctx.llm.complete(lane, system, prompt, out), timeout=_TIMEOUT_S)
        except ValidationError as e:
            await trace.record_llm_call(ctx.writer, run_id, _failed(lane))
            if attempt == 2:
                raise LlmUnavailable(f"{lane} model answered unparseable JSON twice") from e
            prompt = f"{user}\n\nYour previous answer did not match the schema:\n{e}\nAnswer again with valid JSON."
            continue
        except Exception as e:   # timeout, transport, provider: one place turns them into LlmUnavailable
            await trace.record_llm_call(ctx.writer, run_id, _failed(lane))
            raise LlmUnavailable(f"{lane} model unavailable: {e}") from e
        call_id = await trace.record_llm_call(ctx.writer, run_id, trace.LlmCall(
            id=_call_id(), lane=lane, model_requested=completion.model_requested,
            model_answered=completion.model_answered, latency_ms=completion.latency_ms,
            prompt_tokens=completion.prompt_tokens, completion_tokens=completion.completion_tokens, ok=True))
        if run_id is not None:
            await trace.append(ctx.writer, run_id, LlmCalled(actor="llm", llm_call_id=call_id, lane=lane,
                                                            model_answered=completion.model_answered),
                               llm_call_ids=(call_id,))
        return completion
    raise AssertionError("unreachable")


_TIMEOUT_S = 180


def _call_id() -> str:
    return f"llm_{uuid.uuid4().hex}"


def _failed(lane: Lane):
    from app import trace
    return trace.LlmCall(id=_call_id(), lane=lane, model_requested="unknown", model_answered="none", latency_ms=0,
                         prompt_tokens=0, completion_tokens=0, ok=False)


class LlmUnavailable(Exception): ...
