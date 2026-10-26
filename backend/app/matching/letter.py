"""Judge a trial's criteria against the regions of a parsed letter.

A met or not-met answer has to name a region that is actually on the letter. The quote stored with
the answer is that region's text. Unknown is kept when the letter does not settle the criterion.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from app.ctx import Ctx
from app.llm import Lane, complete
from app.matching.clock import Washout, clock_text, measure
from app.matching.types import CriterionResult, Outcome, ValidatedResults
from app.matching.verdict import derive_outcome
from app.record import INTAKE_KINDS, LetterSpan, PatientId, letter_spans
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


ASK_SYSTEM = """You answer one question about one clinical trial for the patient in this letter.
The criteria and the letter regions are the only information you may use. Each region and each criterion has an id.
standing is eligible, possible, excluded, or needs_information.
eligible means the letter meets the inclusions and does not show an exclusion. excluded means the letter shows a failed inclusion or a met exclusion.
possible means some criteria are unsettled but nothing on the letter rules the patient out. needs_information means the letter is missing something they would have to bring.
span_ids lists at most four region ids, the ones whose words most directly support the answer. to_gather lists the missing facts, tests, or dates, each as one short line. Do not list anything the letter already states. Use an empty list when nothing is missing.
The user message has a Clock tool. It is today's date and the measured days from each dated treatment to today. When an exclusion forbids a treatment within N days, weeks, or months, use those numbers. If the clock says the washout has passed, do not put that exclusion in misses. An exclusion with no time window is unchanged.
misses lists exclusion criteria the letter shows the patient meets, so that line rules them out. Each miss has criterion_id, clause, span_id, and why.
clause is a short verbatim excerpt of that exclusion: the specific line that does not fit, not a paraphrase. span_id is the letter region that shows the patient has what that line excludes. why is one sentence.
Leave misses empty when the letter does not show any exclusion. Do not include an exclusion the letter does not settle, and do not include an inclusion.
Do not invent a region id, a criterion id, a date, a drug, or a result. answer is at most four sentences and states only the conclusion."""


class _Miss(BaseModel):
    criterion_id: str
    clause: str = ""
    span_id: str | None = None
    why: str = ""


class _Ask(BaseModel):
    standing: Literal["eligible", "possible", "excluded", "needs_information"]
    answer: str = ""
    to_gather: list[str] = Field(default_factory=list)
    span_ids: list[str] = Field(default_factory=list)
    misses: list[_Miss] = Field(default_factory=list)


@dataclass(frozen=True)
class TrialCitation:
    span_id: str
    document_hash: str
    filename: str
    page: int
    quote: str
    x0: float
    y0: float
    x1: float
    y1: float


@dataclass(frozen=True)
class CriterionMiss:
    """An exclusion the letter shows. clause is a verbatim excerpt of the stored criterion."""
    criterion_id: str
    clause: str
    why: str
    citation: TrialCitation


@dataclass(frozen=True)
class TrialAsk:
    nct_id: str
    title: str
    question: str
    standing: Literal["eligible", "possible", "excluded", "needs_information"]
    answer: str
    to_gather: tuple[str, ...]
    citations: tuple[TrialCitation, ...]
    misses: tuple[CriterionMiss, ...]
    washouts: tuple[Washout, ...]
    via: str


def _excerpt(criterion_text: str, clause: str) -> str | None:
    """The clause as it appears in the criterion, or None when it is not a verbatim excerpt."""
    source = " ".join(criterion_text.split())
    wanted = " ".join(clause.split())
    if len(wanted) < 12:
        return None
    start = source.casefold().find(wanted.casefold())
    if start < 0:
        return None
    return source[start:start + len(wanted)]


def _cite(span: LetterSpan) -> TrialCitation:
    return TrialCitation(span_id=span.id, document_hash=span.document_hash, filename=span.filename, page=span.page,
                         quote=span.text, x0=span.x0, y0=span.y0, x1=span.x1, y1=span.y1)


def ask_prompt(question: str, title: str, criteria: tuple[Criterion, ...], spans: tuple[LetterSpan, ...],
               today: date) -> str:
    """The Regions the Intake agent reads (INTAKE_KINDS): a report's findings are often List-items or a Table, so
    reading only Text would hide them. Page headers, page footers and pictures are letterhead, not evidence.
    The clock is already calculated for today."""
    criteria_lines = [f"[{c.id}] {c.kind}: {' '.join(c.text.split())}" for c in criteria] or ["(no criteria stored)"]
    regions = _regions(tuple(span for span in spans if span.kind in INTAKE_KINDS))
    return (f"Question: {question}\n\n{clock_text(criteria, spans, today)}\n\nTrial: {title}\n\nCriteria:\n"
            + "\n".join(criteria_lines) + f"\n\nRegions:\n{regions}")


def ground_ask(nct_id: str, title: str, question: str, spans: tuple[LetterSpan, ...], criteria: tuple[Criterion, ...],
               item: _Ask, via: str, *, today: date) -> TrialAsk:
    """Drop invented region ids, invented exclusion lines, and washouts the clock says have passed."""
    by_span = {span.id: span for span in spans}
    by_criterion = {c.id: c for c in criteria if str(c.kind) == "exclusion"}
    washouts = measure(criteria, spans, today)
    passed = {row.criterion_id for row in washouts if row.cleared}
    misses: list[CriterionMiss] = []
    seen: set[str] = set()
    for miss in item.misses:
        criterion = by_criterion.get(miss.criterion_id)
        span = by_span.get(miss.span_id) if miss.span_id else None
        clause = _excerpt(criterion.text, miss.clause) if criterion else None
        if criterion is None or span is None or clause is None or criterion.id in seen or criterion.id in passed:
            continue
        seen.add(criterion.id)
        misses.append(CriterionMiss(criterion_id=criterion.id, clause=clause, why=" ".join(miss.why.split()),
                                    citation=_cite(span)))
    cited_ids = list(dict.fromkeys([*item.span_ids, *(m.citation.span_id for m in misses),
                                    *(row.span_id for row in washouts)]))
    citations = tuple(_cite(span) for span_id in cited_ids if (span := by_span.get(span_id)) is not None)
    standing = item.standing
    answer = " ".join(item.answer.split())
    if standing == "excluded" and not misses and passed:
        standing = "possible"
        answer = f"Measured from {today.isoformat()}, the dated treatments fall outside those time windows. {answer}".strip()
    if standing in ("eligible", "excluded") and not citations:
        standing = "needs_information"
        answer = answer or "The letter does not show enough to decide."
    gather = tuple(" ".join(line.split()) for line in item.to_gather if line.strip())
    return TrialAsk(nct_id=nct_id, title=title, question=question, standing=standing,
                    answer=answer or "The letter does not settle this.", to_gather=gather, citations=citations,
                    misses=tuple(misses), washouts=washouts, via=via)


async def ask_trial(ctx: Ctx, patient_id: str, nct_id: str, question: str) -> TrialAsk:
    """Answer one question about one stored trial. Criteria and letter regions are read through the agent reader."""
    from app.record import NotFound
    from app.sql.reader import ZetarisReader

    spans = await letter_spans(ctx, PatientId(patient_id), for_agent=True)
    trial = await trials.trial(ctx, NctId(nct_id), for_agent=True)
    if trial is None:
        raise NotFound(f"no Trial {nct_id}")
    criteria = await trials.criteria(ctx, NctId(nct_id), for_agent=True)
    today = ctx.now().date()
    completion = await complete(
        ctx, Lane.DEEP, system=ASK_SYSTEM, user=ask_prompt(question, trial.title, criteria, spans, today),
        out=_Ask, run_id=None)
    via = "zetaris" if isinstance(ctx.agent_reader, ZetarisReader) else "postgres"
    return ground_ask(trial.nct_id, trial.title, question, spans, criteria, completion.value, via, today=today)


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
