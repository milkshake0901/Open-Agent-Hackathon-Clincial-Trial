"""app/matching — MATCHING module. Public surface.

Owns: Criterion results, Verdicts, Doctor questions, the Matcher⇄Evaluator loop, Re-scan.
Hides: parallelism, idempotent planning, citation validation, verdict derivation, question generation.
"""
from __future__ import annotations

from app import record, trace
from app.ctx import Ctx
from app.matching import loop, repo
from app.matching.types import (
    Citation, CriterionResult, DoctorQuestion, Outcome, RescanReport, Verdict, VerdictChange, VerdictOutcome,
)
from app.record import ProfileVersionId
from app.trials import NctId
from app.trace import RunId

__all__ = ["rescan", "verdict", "verdicts_for_version", "change_between", "questions_for_version",
           "Verdict", "DoctorQuestion", "RescanReport", "VerdictChange", "VerdictOutcome", "Outcome",
           "CriterionResult", "Citation"]

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


async def verdict(ctx: Ctx, nct_id: NctId, version_id: ProfileVersionId) -> Verdict | None:
    """With criterion results, citations (fact + document + page + quote + question) and doctor questions.
    The Verdict judged against the Trial's current Criteria."""
    return await repo.verdict(ctx.ui_reader, nct_id, version_id, with_results=True)


async def verdicts_for_version(ctx: Ctx, version_id: ProfileVersionId) -> list[Verdict]:
    """Ranked: eligible, then possible (fewest unknowns first), then excluded; ties by NCT id.
    Results, Citations and questions are loaded (the Trials page shows them)."""
    ranked = sorted(await repo.verdicts_for_version(ctx.ui_reader, version_id),
                    key=lambda vu: (_RANK[vu[0].outcome], vu[1] if vu[0].outcome == VerdictOutcome.POSSIBLE else 0,
                                    vu[0].nct_id))
    return [v for v, _ in ranked]


async def change_between(ctx: Ctx, nct_id: NctId, from_version: ProfileVersionId, to_version: ProfileVersionId) -> VerdictChange:
    """Why did the Verdict move? Pure diff of two stored Verdicts' criterion results. The demo moment."""
    raise NotImplementedError


async def questions_for_version(ctx: Ctx, version_id: ProfileVersionId) -> list[DoctorQuestion]:
    """Deduplicated across Trials by criterion subject; each carries the Trials it would unblock (`unblocks`).
    The first occurrence (Trial, then Criterion order) supplies criterion_id, nct_id and text."""
    from dataclasses import replace

    first: dict[str, DoctorQuestion] = {}
    trials_by_subject: dict[str, list[NctId]] = {}
    for q in await repo.questions_for_version(ctx.ui_reader, version_id):
        key = q.subject.lower()
        first.setdefault(key, q)
        if q.nct_id not in trials_by_subject.setdefault(key, []):
            trials_by_subject[key].append(q.nct_id)
    return [replace(q, unblocks=tuple(trials_by_subject[k])) for k, q in first.items()]
