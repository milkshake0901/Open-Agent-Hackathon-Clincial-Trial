"""app/llm — LLM gateway. One function. Owns lanes, provider, structured parsing, model_answered logging.

Agents are LangChain agents: they take their model from `ctx.llm.chat_model(lane)` (Nightshift), so
the provider, headers and Nemotron lane pinning live here and nowhere else. Media generation on a
Meterless job is `Media` (app/llm/media.py)."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Generic, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

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


class LLM(Protocol):
    async def complete(self, lane: Lane, system: str, user: str, out: type[T]) -> Completion[T]: ...
    def chat_model(self, lane: Lane | None = None) -> "BaseChatModel":
        """LangChain chat model on the lane's pinned model; agents are built on this."""
        ...


async def complete(ctx, lane: Lane, *, system: str, user: str, out: type[T], run_id: RunId | None) -> Completion[T]:
    """JSON-mode call, parse into `out`; ONE transport-level retry on parse failure with the validation error
    appended (this is not a domain loop and is not traced as one). Records an llm_call row and emits LlmCalled to the run when run_id given.
    Timeout 180 s (model load). Raises LlmUnavailable after that; loops treat it as a failed Trial / Rejected run."""
    try:
        try:
            done = await ctx.llm.complete(lane, system, user, out)
        except ValidationError as e:
            retry = f"{user}\n\nYour previous reply did not match the schema:\n{e}\nReply with the corrected JSON object only."
            done = await ctx.llm.complete(lane, system, retry, out)
    except ValidationError as e:
        raise LlmUnavailable(f"{lane} lane reply did not parse twice: {e.error_count()} errors") from e
    if run_id is not None:
        from app import trace
        from app.trace.events import LlmCalled

        call_id = await trace.record_llm_call(ctx.writer, run_id, trace.LlmCall(
            id=uuid.uuid4().hex, lane=lane.value, model_requested=done.model_requested,
            model_answered=done.model_answered, latency_ms=done.latency_ms,
            prompt_tokens=done.prompt_tokens, completion_tokens=done.completion_tokens, ok=True))
        await trace.append(ctx.writer, run_id, LlmCalled(actor="llm", llm_call_id=call_id, lane=lane.value,
                                                         model_answered=done.model_answered),
                           llm_call_ids=(call_id,))
    return done


class LlmUnavailable(Exception): ...


from app.llm.media import Media, MediaFailed, MediaKind, MediaUnavailable, Plan, StoredMedia  # noqa: E402
