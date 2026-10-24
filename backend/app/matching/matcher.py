"""app/matching/matcher.py — Matcher agent: Criteria × current Facts (+ rejections) → CriterionResults. Deep lane."""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel

from app.ctx import Ctx
from app.llm import Lane, complete
from app.matching import distance
from app.matching.types import Citation, CriterionResult, Outcome, Rejection, SiteDistance
from app.record import Fact, ProfileVersion
from app.trials import Criterion, CriterionId, Trial
from app import trace
from app.trace.events import MatcherProposed


class _ResultOut(BaseModel):
    criterion_id: str
    outcome: str                 # met | not_met | unknown
    fact_id: str | None = None   # must be one of the ids listed in the prompt
    rationale: str


class _MatchOut(BaseModel):
    results: list[_ResultOut]


SYSTEM = """You are the Matcher agent of a clinical-trial matching service. For ONE Trial you judge each eligibility
Criterion against the patient's current Facts. Answer with JSON only:
{"results": [{"criterion_id": "...", "outcome": "met" | "not_met" | "unknown", "fact_id": "..." | null,
              "rationale": "one plain sentence"}]}
- Give exactly one result per Criterion listed, using its id.
- "met" means what the Criterion text describes is true of the patient; "not_met" means it is false. For an
  exclusion Criterion, "met" means the patient HAS what it excludes (so they are excluded).
- "met" and "not_met" must cite the ONE Fact (by its id, from the list) that shows it. Never cite an id that is not
  listed, and never answer from general knowledge.
- If the Facts do not settle a Criterion, answer "unknown" with fact_id null. Unknown is a good answer: it becomes
  a question for the patient's doctor.
- Patient-reported Facts quote the Respondent's own words. If the words are too vague to decide, answer "unknown".
"""

BIRTH_MONTH = "birth month"   # the record's Patient Fact; age is derived here, at matching time, never stored


def _age(birth_month: str, today: date) -> int | None:
    try:
        year, month = (int(x) for x in birth_month.split("-")[:2])
    except ValueError:
        return None
    return today.year - year - (today.month < month)


def _source(f: Fact) -> str:
    return f"Patient-reported, intake questionnaire, {f.question}" if f.question else f"document page {f.page}"


SITES_SHOWN = 5


def _site_lines(sites: tuple[SiteDistance, ...]) -> list[str]:
    """Sites as "name · status · km" only, nearest first (ADR 0003: the postcode never reaches a model)."""
    if not sites:
        return []
    lines = ["", "Sites (distance from the patient's area; context only, distance never decides a Criterion):"]
    lines += [f"- {distance.line(sd)}" for sd in sites[:SITES_SHOWN]]
    if len(sites) > SITES_SHOWN:
        lines.append(f"- and {len(sites) - SITES_SHOWN} more sites further away")
    return lines


def _prompt(trial: Trial, criteria: tuple[Criterion, ...], profile: ProfileVersion, feedback: tuple[Rejection, ...],
            today: date, sites: tuple[SiteDistance, ...] = ()) -> str:
    lines = [f"Trial {trial.nct_id}: {trial.title}", "", "Criteria:"]
    lines += [f"- {c.id} [{c.kind}] {c.text}" for c in criteria]
    lines += _site_lines(sites)
    lines += ["", f"Facts (Profile version {profile.number}, today is {today.isoformat()}):"]
    current = profile.current()
    for f in current.values():
        unit = f" {f.unit}" if f.unit else ""
        lines.append(f'- {f.id} | {f.subject}: {f.value}{unit} | observed {f.observed_on.isoformat()} | '
                     f'{_source(f)} | quote "{f.quote}"')
        if f.subject == BIRTH_MONTH and (age := _age(f.value, today)) is not None:
            lines.append(f"  (so the patient is {age} years old today; cite {f.id} for age)")
    if not current:
        lines.append("- (no Facts yet)")
    if feedback:
        lines += ["", "Your previous answer was rejected for these Criteria. Fix them and answer for every Criterion again:"]
        lines += [f"- criterion {r.criterion_id}: previous answer rejected because {r.reason}" for r in feedback]
    return "\n".join(lines)


def _outcome(raw: str) -> Outcome:
    try:
        return Outcome(raw.strip().lower())
    except ValueError:
        return Outcome.UNKNOWN


async def propose(ctx: Ctx, trial: Trial, criteria: tuple[Criterion, ...], profile: ProfileVersion,
                  feedback: tuple[Rejection, ...], run_id: trace.RunId, attempt: int = 1) -> tuple[CriterionResult, ...]:
    """Prompt lists Criteria with ids and profile.current() Facts with ids; the model may only cite listed ids.
    Rejections from the Evaluator are rendered as 'criterion C3: previous answer rejected because ...'.
    Citation provenance (document_hash, page, quote) is filled from the Fact here, never by the model; a cited id
    that is not a Fact of this version gets an empty provenance, which the Evaluator rejects.
    Results for ids that are not Criteria of this Trial are dropped. Emits MatcherProposed with model_answered."""
    sites = (await distance.reach_of(ctx, trial.nct_id, await distance.origin(ctx, profile.patient_id))).sites
    completion = await complete(ctx, Lane.DEEP, system=SYSTEM, user=_prompt(trial, criteria, profile, feedback,
                                                                            ctx.now().date(), sites),
                                out=_MatchOut, run_id=run_id)
    ids = {c.id for c in criteria}
    facts = {f.id: f for f in profile.facts}
    results = []
    for r in completion.value.results:
        if r.criterion_id not in ids:
            continue
        citation = None
        if r.fact_id:
            f = facts.get(r.fact_id)
            citation = (Citation(fact_id=f.id, document_hash=f.document_hash, page=f.page, quote=f.quote,
                                 question=f.question) if f else
                        Citation(fact_id=r.fact_id, document_hash="", page=0, quote=""))
        results.append(CriterionResult(criterion_id=CriterionId(r.criterion_id), outcome=_outcome(r.outcome),
                                       citation=citation, rationale=r.rationale.strip()))
    await trace.append(ctx.writer, run_id, MatcherProposed(
        actor="matcher", nct_id=trial.nct_id, attempt=attempt, model_answered=completion.model_answered,
        results=[{"criterion_id": r.criterion_id, "outcome": str(r.outcome),
                  "fact_id": r.citation.fact_id if r.citation else None, "rationale": r.rationale} for r in results]))
    return tuple(results)

