"""app/matching — MATCHING module. Public surface.

Owns: Criterion results, Verdicts, Doctor questions, the Matcher⇄Evaluator loop, Re-scan.
Hides: parallelism, idempotent planning, citation validation, verdict derivation, question generation.
"""
from __future__ import annotations

from app.ctx import Ctx
from app.matching.types import DoctorQuestion, RescanReport, Verdict, VerdictChange
from app.record import ProfileVersionId
from app.trials import NctId
from app.trace import RunId

__all__ = ["rescan", "verdict", "verdicts_for_version", "change_between", "questions_for_version",
           "Verdict", "DoctorQuestion", "RescanReport", "VerdictChange"]


async def rescan(ctx: Ctx, version_id: ProfileVersionId, *, only: set[NctId] | None = None,
                 run_id: RunId | None = None) -> RescanReport:
    """Produce a Verdict for every active Trial that lacks one for (trial, version, trial.eligibility_hash).

    Idempotent and cheap: the plan is a set difference computed in SQL; Trials already judged
    for this version with the current eligibility hash are skipped without a model call.
    `only` narrows to Trials that trials.sync reported changed. Runs Trials with bounded
    concurrency; each Verdict commits in its own transaction, so a crash loses at most the
    in-flight Trials and the next rescan finishes the rest.
    """
    raise NotImplementedError


async def verdict(ctx: Ctx, nct_id: NctId, version_id: ProfileVersionId) -> Verdict | None:
    """With criterion results, citations (fact + document + page + quote) and doctor questions."""
    raise NotImplementedError


async def verdicts_for_version(ctx: Ctx, version_id: ProfileVersionId) -> list[Verdict]:
    """Ranked: eligible, then possible (fewest unknowns first), then excluded. Results not loaded."""
    raise NotImplementedError


async def change_between(ctx: Ctx, nct_id: NctId, from_version: ProfileVersionId, to_version: ProfileVersionId) -> VerdictChange:
    """Why did the Verdict move? Pure diff of two stored Verdicts' criterion results. The demo moment."""
    raise NotImplementedError


async def questions_for_version(ctx: Ctx, version_id: ProfileVersionId) -> list[DoctorQuestion]:
    """Deduplicated across Trials by criterion subject; each carries the Trials it would unblock."""
    raise NotImplementedError
