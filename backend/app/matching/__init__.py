"""app/matching — MATCHING module. Public surface.

Owns: Criterion results, Verdicts, Doctor questions, Respondent questions, the Matcher⇄Evaluator loop, Re-scan.
Hides: parallelism, idempotent planning, citation validation, verdict derivation, question generation.
"""
from __future__ import annotations

from app import record, trace, trials
from app.ctx import Ctx
from app.matching import distance, loop, repo
from app.matching.types import (
    Citation, CriterionResult, DoctorQuestion, Outcome, RescanReport, RespondentQuestion, TrialSiteDistance, Verdict,
    VerdictChange, VerdictOutcome,
)
from app.record import ProfileVersionId
from app.trials import NctId
from app.trace import RunId

__all__ = ["rescan", "km", "CLOSED_SITE", "verdict", "verdicts_for_version", "change_between", "questions_for_version",
           "respondent_questions_for_version", "Verdict", "DoctorQuestion", "RespondentQuestion", "RescanReport",
           "VerdictChange", "VerdictOutcome", "Outcome", "CriterionResult", "Citation", "TrialSiteDistance"]

# Distance from a coarse location point to a Trial site, and the site statuses that will never take a patient; for
# other modules that rank Trial sites the way matching does (an Enquiry's nearest site contact).
km = distance.km
CLOSED_SITE = distance.CLOSED_SITE

DIAGNOSIS_QUESTION = "diagnosis"   # the questionnaire question (Q6) a Diagnosis check reads
_RANK = {VerdictOutcome.ELIGIBLE: 0, VerdictOutcome.POSSIBLE: 1, VerdictOutcome.EXCLUDED: 2}


async def rescan(ctx: Ctx, version_id: ProfileVersionId, *, only: set[NctId] | None = None,
                 run_id: RunId | None = None, correlation_id: RunId | None = None) -> RescanReport:
    """Produce a Verdict for every active Trial that lacks one for (trial, version, trial.eligibility_hash).

    Idempotent and cheap: the plan is a set difference computed in SQL; Trials already judged
    for this version with the current eligibility hash are skipped without a model call.
    `only` narrows to Trials that trials.sync reported changed. Runs Trials with bounded
    concurrency; each Verdict commits in its own transaction, so a crash loses at most the
    in-flight Trials and the next rescan finishes the rest.
    The rescan run is traced under `correlation_id` (the ingest run that committed the version), if given.
    Raises record.NotFound for an unknown version.
    """
    profile = await record.profile_version(ctx, version_id)
    run_id = run_id or trace.new_id()
    await trace.open(ctx.writer, run_id, "rescan", patient_id=profile.patient_id, correlation_id=correlation_id)
    return await loop.run_rescan(ctx, version_id, only, run_id, ctx.settings.match_attempts,
                                 ctx.settings.match_concurrency)


async def _with_distances(ctx: Ctx, v: Verdict, at: distance.Origin) -> Verdict:
    from dataclasses import replace

    r = await distance.reach_of(ctx, v.nct_id, at)
    return replace(v, nearest_site=r.nearest_recruiting, sites=r.sites, further_away=r.further_away)


async def verdict(ctx: Ctx, nct_id: NctId, version_id: ProfileVersionId) -> Verdict | None:
    """With criterion results, citations (fact + document + page + quote + question) and doctor questions.
    The Verdict judged against the Trial's current Criteria. Site distances as in verdicts_for_version."""
    v = await repo.verdict(ctx.ui_reader, nct_id, version_id, with_results=True)
    if v is None:
        return None
    profile = await record.profile_version(ctx, version_id)
    return await _with_distances(ctx, v, await distance.origin(ctx, profile.patient_id))


async def verdicts_for_version(ctx: Ctx, version_id: ProfileVersionId) -> list[Verdict]:
    """Ranked by outcome: eligible, then possible (fewest unknowns first), then excluded; then by the nearest
    recruiting site (unknown distance last); ties by NCT id. Results, Citations and questions are loaded (the
    Trials page shows them). Each Verdict carries its sites' km from the patient's CURRENT postcode, and Trials
    with no recruiting site within the travel limit are flagged `further_away`, never dropped. Distance only
    orders and flags: the outcome is the stored one, with or without a postcode. Once the patient's diagnosis term
    is confirmed (#14), only Trials that study it are listed, including Verdicts judged before it was confirmed."""
    selected = await _selected(ctx, version_id)
    stored = [vu for vu in await repo.verdicts_for_version(ctx.ui_reader, version_id) if selected(vu[0].nct_id)]
    if not stored:
        return []
    at = await distance.origin(ctx, (await record.profile_version(ctx, version_id)).patient_id)
    located = [(await _with_distances(ctx, v, at), unknowns) for v, unknowns in stored]

    def key(vu: tuple[Verdict, int]):
        v, unknowns = vu
        km = v.nearest_site.km if v.nearest_site and v.nearest_site.km is not None else float("inf")
        return _RANK[v.outcome], unknowns if v.outcome == VerdictOutcome.POSSIBLE else 0, km, v.nct_id
    return [v for v, _ in sorted(located, key=key)]


async def change_between(ctx: Ctx, nct_id: NctId, from_version: ProfileVersionId, to_version: ProfileVersionId) -> VerdictChange:
    """Why did the Verdict move? Pure diff of two stored Verdicts' criterion results. The demo moment.
    Lists the Criteria whose outcome differs (all of them when the Trial was not judged at from_version).
    Raises LookupError when the Trial has no Verdict at to_version."""
    from app import trials
    from app.matching.types import CriterionChange

    after = await verdict(ctx, nct_id, to_version)
    if after is None:
        raise LookupError(f"no Verdict for {nct_id} at {to_version}")
    before = await verdict(ctx, nct_id, from_version)
    was = {r.criterion_id: r.outcome for r in before.results} if before else {}
    texts = {c.id: c.text for c in await trials.criteria(ctx, nct_id)}
    return VerdictChange(nct_id=nct_id, outcome_from=before.outcome if before else None, outcome_to=after.outcome,
                         criteria_changed=tuple(
                             CriterionChange(criterion_id=r.criterion_id, text=texts.get(r.criterion_id, ""),
                                             outcome_from=was.get(r.criterion_id), outcome_to=r.outcome,
                                             citation=r.citation)
                             for r in after.results if was.get(r.criterion_id) != r.outcome))


async def questions_for_version(ctx: Ctx, version_id: ProfileVersionId) -> list[DoctorQuestion]:
    """Deduplicated across Trials by criterion subject; each carries the Trials it would unblock (`unblocks`).
    The first occurrence (Trial, then Criterion order) supplies criterion_id, nct_id and text. Only Trials selected
    by a confirmed diagnosis term count (#14). When the diagnosis needs the GP ("not sure", or no confident term),
    a patient-level question for the diagnosis comes first: criterion_id and nct_id None, subject "diagnosis"."""
    from dataclasses import replace

    profile = await record.profile_version(ctx, version_id)
    held = await record.diagnosis(ctx, profile.patient_id)
    selected = _selector(held.condition_term if held else None, await trials.active_trials(ctx))
    first: dict[str, DoctorQuestion] = {}
    if held is not None and held.needs_gp:
        first["\0diagnosis"] = DoctorQuestion(
            criterion_id=None, nct_id=None, subject="diagnosis",
            text=f"Please confirm the patient's diagnosis and its exact name. In their own words: \"{held.text}\".")
    trials_by_subject: dict[str, list[NctId]] = {}
    for q in await repo.questions_for_version(ctx.ui_reader, version_id):
        if not selected(q.nct_id):
            continue
        key = q.subject.lower()
        first.setdefault(key, q)
        if q.nct_id not in trials_by_subject.setdefault(key, []):
            trials_by_subject[key].append(q.nct_id)
    return [replace(q, unblocks=tuple(trials_by_subject.get(k, ()))) for k, q in first.items()]


def _selector(condition_term: str | None, active: list[trials.Trial]):
    if condition_term is None:
        return lambda nct_id: True
    chosen = {t.nct_id for t in active if trials.studies_condition(t, condition_term)}
    return lambda nct_id: nct_id in chosen


async def _selected(ctx: Ctx, version_id: ProfileVersionId):
    """Which Trials the version's patient is matched against: all, or those studying the confirmed diagnosis."""
    profile = await record.profile_version(ctx, version_id)
    return _selector(await loop.condition_term_for(ctx, profile.patient_id), await trials.active_trials(ctx))


async def respondent_questions_for_version(ctx: Ctx, version_id: ProfileVersionId) -> list[RespondentQuestion]:
    """Deduplicated across Trials by subject (the questionnaire question); each carries the Trials it would unblock.
    The first occurrence (Trial, then Criterion order) supplies criterion_id, nct_id and text. Answering one is a
    questionnaire resubmission: the new Profile version is re-scanned and gets its own Verdicts and questions.
    Only Trials selected by a confirmed diagnosis term count (#14), as for Doctor questions. While the diagnosis
    needs the GP, the diagnosis question is not asked again: the patient-level Doctor question covers it."""
    from dataclasses import replace

    selected = await _selected(ctx, version_id)
    profile = await record.profile_version(ctx, version_id)
    held = await record.diagnosis(ctx, profile.patient_id)
    first: dict[str, RespondentQuestion] = {}
    trials_by_subject: dict[str, list[NctId]] = {}
    for q in await repo.respondent_questions_for_version(ctx.ui_reader, version_id):
        if not selected(q.nct_id) or (held is not None and held.needs_gp and q.question_id == DIAGNOSIS_QUESTION):
            continue
        first.setdefault(q.question_id, q)
        if q.nct_id not in trials_by_subject.setdefault(q.question_id, []):
            trials_by_subject[q.question_id].append(q.nct_id)
    return [replace(q, unblocks=tuple(trials_by_subject[k])) for k, q in first.items()]
