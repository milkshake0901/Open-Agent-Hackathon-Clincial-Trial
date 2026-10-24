"""app/matching/matcher.py — Matcher agent: Criteria × current Facts (+ rejections) → CriterionResults. Deep lane."""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel

from app.ctx import Ctx
from app.llm import Lane, complete
from app.matching.types import Citation, CriterionResult, Outcome, Rejection
from app import record
from app.record import Fact, ProfileVersion, Question
from app.trials import Criterion, CriterionId, Trial
from app import trace
from app.trace.events import MatcherProposed


class _ResultOut(BaseModel):
    criterion_id: str
    outcome: str                 # met | not_met | unknown
    fact_id: str | None = None   # must be one of the ids listed in the prompt
    rationale: str
    ask: str | None = None       # unknown only: a questionnaire question number for the Respondent


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
- On an "unknown" that turns on something the Respondent could know (a date, a medicine name) but answered too
  vaguely or not at all, set "ask" to the number of the questionnaire question they should answer again ("Q8").
  Leave "ask" null when it needs clinical records or judgement (labs, stage, scans): the doctor is asked instead.
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


def askable() -> dict[str, Question]:
    """Questionnaire questions a Respondent question may point back at, by number: the ones that become Facts."""
    return {q.ref: q for q in record.questionnaire_definition().questions() if q.use in ("fact", "free_text")}


def _askable_lines() -> list[str]:
    return ["", "Questionnaire questions the Respondent can answer again:"] + [
        f"- {ref} {q.label}" for ref, q in askable().items()]


def _prompt(trial: Trial, criteria: tuple[Criterion, ...], profile: ProfileVersion, feedback: tuple[Rejection, ...],
            today: date) -> str:
    lines = [f"Trial {trial.nct_id}: {trial.title}", "", "Criteria:"]
    lines += [f"- {c.id} [{c.kind}] {c.text}" for c in criteria]
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
    lines += _askable_lines()
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
    completion = await complete(ctx, Lane.DEEP, system=SYSTEM, user=_prompt(trial, criteria, profile, feedback,
                                                                            ctx.now().date()),
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
        outcome = _outcome(r.outcome)
        ask = (r.ask or "").strip().upper()
        results.append(CriterionResult(criterion_id=CriterionId(r.criterion_id), outcome=outcome,
                                       citation=citation, rationale=r.rationale.strip(),
                                       ask=ask if outcome == Outcome.UNKNOWN and ask in askable() else None))
    await trace.append(ctx.writer, run_id, MatcherProposed(
        actor="matcher", nct_id=trial.nct_id, attempt=attempt, model_answered=completion.model_answered,
        results=[{"criterion_id": r.criterion_id, "outcome": str(r.outcome),
                  "fact_id": r.citation.fact_id if r.citation else None, "rationale": r.rationale, "ask": r.ask}
                 for r in results]))
    return tuple(results)

