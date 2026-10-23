"""app/llm — LLM gateway. One function. Owns lanes, provider, structured parsing, model_answered logging."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Generic, Protocol, TypeVar

from pydantic import BaseModel

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
    raise NotImplementedError


class LlmUnavailable(Exception): ...
