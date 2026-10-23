"""app/matching/matcher.py — Matcher agent: Criteria × current Facts (+ rejections) → CriterionResults. Deep lane."""
from __future__ import annotations

from pydantic import BaseModel

from app.ctx import Ctx
from app.llm import Lane, complete
from app.matching.types import CriterionResult, Rejection
from app.record import ProfileVersion
from app.trials import Criterion, Trial
from app import trace


class _ResultOut(BaseModel):
    criterion_id: str
    outcome: str                 # met | not_met | unknown
    fact_id: str | None = None   # must be one of the ids listed in the prompt
    rationale: str


class _MatchOut(BaseModel):
    results: list[_ResultOut]


async def propose(ctx: Ctx, trial: Trial, criteria: tuple[Criterion, ...], profile: ProfileVersion,
                  feedback: tuple[Rejection, ...], run_id: trace.RunId) -> tuple[CriterionResult, ...]:
    """Prompt lists Criteria with ids and profile.current() Facts with ids; the model may only cite listed ids.
    Rejections from the Evaluator are rendered as 'criterion C3: previous answer rejected because ...'.
    Citation provenance (document_hash, page, quote) is filled from the Fact here, never by the model.
    Emits MatcherProposed with model_answered."""
    raise NotImplementedError
