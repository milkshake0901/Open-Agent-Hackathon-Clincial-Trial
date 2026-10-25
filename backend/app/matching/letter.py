"""Judge a trial's criteria against the regions of a parsed letter.

A met or not-met answer has to name a region that is actually on the letter. The quote stored with
the answer is that region's text. Unknown is kept when the letter does not settle the criterion.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from app.ctx import Ctx
from app.llm import Lane, complete
from app.matching.types import CriterionResult, Outcome, ValidatedResults
from app.matching.verdict import derive_outcome
from app.record import LetterSpan, PatientId, letter_spans
from app.trials import Criterion, NctId
from app import trials

SYSTEM = """You judge one clinical trial's eligibility criteria against regions of a referral letter.
Each criterion and each region has an id. The words in a region are the only evidence you may use.
outcome is met, not_met, or unknown.
For an inclusion criterion, met means the letter shows the patient meets it. For an exclusion criterion, met means the letter shows the patient has what it excludes.
met and not_met must set span_id to a region id whose words show that. If the letter does not settle the criterion, outcome is unknown and span_id is null.
Do not invent a region id, a date, or a drug. rationale is one sentence.
Reply with one result per criterion id listed."""


class _Item(BaseModel):
    criterion_id: str
    outcome: Literal["met", "not_met", "unknown"]
    span_id: str | None = None
    rationale: str = ""


class _Screen(BaseModel):
    results: list[_Item] = Field(default_factory=list)


@dataclass(frozen=True)
class CriterionScreen:
    criterion_id: str
    kind: str
    text: str
    outcome: Literal["met", "not_met", "unknown"]
    rationale: str
    span_id: str | None
    page: int | None
    quote: str | None
    x0: float | None
    y0: float | None
    x1: float | None
    y1: float | None


@dataclass(frozen=True)
class TrialScreen:
    nct_id: str
    title: str
    outcome: Literal["eligible", "possible", "excluded"]
    criteria: tuple[CriterionScreen, ...]


def _regions(spans: tuple[LetterSpan, ...]) -> str:
    lines: list[str] = []
    seen: set[str] = set()
    for span in spans:
        text = " ".join(span.text.split())
        if span.kind == "Page-footer" or not text:
            continue
        key = text.casefold()
        if span.kind == "Caption" and key in seen:
            continue
        seen.add(key)
        lines.append(f"[{span.id}] {text}")
    return "\n".join(lines)


def screen_prompt(title: str, criteria: tuple[Criterion, ...], spans: tuple[LetterSpan, ...]) -> str:
    lines = [f"[{c.id}] {c.kind}: {c.text}" for c in criteria]
    return f"Trial: {title}\n\nCriteria:\n" + "\n".join(lines) + f"\n\nRegions:\n{_regions(spans)}"


def apply_screen(criteria: tuple[Criterion, ...], spans: tuple[LetterSpan, ...],
                 items: list[_Item]) -> tuple[CriterionScreen, ...]:
    """Keep one row per criterion. A decisive answer whose region is not on the letter becomes unknown."""
    by_span = {span.id: span for span in spans}
    by_item: dict[str, _Item] = {}
    for item in items:
        if item.criterion_id not in {c.id for c in criteria} or item.criterion_id in by_item:
            continue
        by_item[item.criterion_id] = item
    judged: list[CriterionScreen] = []
    for criterion in criteria:
        item = by_item.get(criterion.id)
        span = by_span.get(item.span_id) if item and item.span_id else None
        outcome: Literal["met", "not_met", "unknown"] = item.outcome if item else "unknown"
        rationale = (item.rationale if item else "").strip()
        if outcome in ("met", "not_met") and span is None:
            outcome = "unknown"
            rationale = "The letter does not show this."
        judged.append(CriterionScreen(
            criterion_id=criterion.id, kind=str(criterion.kind), text=criterion.text, outcome=outcome,
            rationale=rationale or "The letter does not show this.",
            span_id=span.id if span and outcome != "unknown" else None,
            page=span.page if span and outcome != "unknown" else None,
            quote=span.text if span and outcome != "unknown" else None,
            x0=span.x0 if span and outcome != "unknown" else None,
            y0=span.y0 if span and outcome != "unknown" else None,
            x1=span.x1 if span and outcome != "unknown" else None,
            y1=span.y1 if span and outcome != "unknown" else None,
        ))
    return tuple(judged)


def _outcome(criteria: tuple[Criterion, ...], judged: tuple[CriterionScreen, ...]) -> Literal["eligible", "possible", "excluded"]:
    if not criteria:
        return "possible"
    results = ValidatedResults(tuple(
        CriterionResult(criterion_id=row.criterion_id, outcome=Outcome(row.outcome), citation=None, rationale=row.rationale)
        for row in judged))
    return derive_outcome(results, criteria).value


async def screen_letter(ctx: Ctx, patient_id: str, nct_ids: list[str]) -> tuple[TrialScreen, ...]:
    """One model call per trial. Raises NotFound when the patient has no parsed letter."""
    spans = await letter_spans(ctx, PatientId(patient_id))
    screens: list[TrialScreen] = []
    for nct_id in nct_ids:
        trial = await trials.trial(ctx, NctId(nct_id))
        if trial is None:
            continue
        criteria = await trials.criteria(ctx, NctId(nct_id))
        if not criteria:
            screens.append(TrialScreen(nct_id=trial.nct_id, title=trial.title, outcome="possible", criteria=()))
            continue
        completion = await complete(
            ctx, Lane.DEEP, system=SYSTEM, user=screen_prompt(trial.title, criteria, spans),
            out=_Screen, run_id=None)
        judged = apply_screen(criteria, spans, completion.value.results)
        screens.append(TrialScreen(nct_id=trial.nct_id, title=trial.title, outcome=_outcome(criteria, judged),
                                   criteria=judged))
    return tuple(screens)
