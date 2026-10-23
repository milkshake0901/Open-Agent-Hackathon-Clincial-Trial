"""app/matching/loop.py — JudgeTrialLoop (Matcher⇄Evaluator) + Re-scan planner/runner.

Same shape as record.loop: closed step set, bound as a field, exhaustion is a transition.
Per-Trial loop steps are appended to the rescan run's trace (parallel Matcher tasks append
concurrently); each approved Verdict is written to the World Model as a patient→trial relationship.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from app.ctx import Ctx
from app.matching import evaluator, matcher, repo, verdict as verdict_rules
from app.worldmodel import timeline
from app.matching.types import CriterionResult, Rejection, RescanReport, ValidatedResults, Verdict
from app.record import ProfileVersion, ProfileVersionId
from app.trials import Criterion, NctId, Trial
from app import trace
from app.trace.events import EvaluatorApproved, EvaluatorRejected, MatcherRetried, RescanPlanned, TrialJudged, RescanFinished


@dataclass(frozen=True)
class Retry:
    rejections: tuple[Rejection, ...]

@dataclass(frozen=True)
class Approve:
    results: ValidatedResults

@dataclass(frozen=True)
class Exhausted:
    """Bound reached: unsupported claims will be downgraded, never shipped."""
    last_results: tuple[CriterionResult, ...]
    rejections: tuple[Rejection, ...]

Step = Retry | Approve | Exhausted


def decide(review: evaluator.Review, attempt: int, max_attempts: int) -> Step:
    """PURE loop policy.
    # TODO: Approve if review.rejections empty; Retry if attempt < max; else Exhausted.
    """
    raise NotImplementedError


async def judge_trial(ctx: Ctx, trial: Trial, criteria: tuple[Criterion, ...], profile: ProfileVersion,
                      run_id: trace.RunId, max_attempts: int) -> Verdict:
    """# TODO pseudocode
    #   feedback = ()
    #   for attempt in 1..max_attempts:
    #       results = await matcher.propose(ctx, trial, criteria, profile, feedback, run_id)    # deep lane; emits MatcherProposed
    #       review  = await evaluator.review(ctx, results, criteria, profile, run_id)           # pure checks + judge lane
    #       match decide(review, attempt, max_attempts):
    #           case Approve(vr):   validated = vr; break        (emit EvaluatorApproved)
    #           case Retry(rj):     feedback = rj                (emit EvaluatorRejected + MatcherRetried)
    #           case Exhausted(rs, rj):
    #               validated = evaluator.downgrade(rs, rj)      # unsupported → UNKNOWN; still ValidatedResults
    #   outcome   = verdict_rules.derive_outcome(validated, criteria)
    #   questions = verdict_rules.questions_from_unknowns(validated, criteria, trial)
    #   v = Verdict(..., attempts=attempt, unsupported_downgraded=n)
    #   await timeline.record_verdict(ctx.wm, profile.patient_id, v)   # World Model relate(); projector writes verdict rows
    #   await trace.append(ctx.writer, run_id, TrialJudged(nct, outcome, attempts))   # parallel Matcher tasks append concurrently; seq comes from the DB
    #   return v
    """
    raise NotImplementedError


async def plan(ctx: Ctx, version_id: ProfileVersionId, only: set[NctId] | None) -> tuple[list[Trial], list[NctId]]:
    """(to_judge, skipped). SQL: active trials LEFT JOIN verdict ON (nct, trial.eligibility_hash, version)
    WHERE verdict is null. Reads via ctx.agent_reader (Zetaris). Old-hash Verdicts are kept (ADR 0002)."""
    raise NotImplementedError


async def run_rescan(ctx: Ctx, version_id: ProfileVersionId, only: set[NctId] | None, run_id: trace.RunId,
                     max_attempts: int, concurrency: int) -> RescanReport:
    """# TODO pseudocode
    #   profile = await record.profile_version(ctx, version_id, for_agent=True)   # Zetaris, bounded visibility wait
    #   to_judge, skipped = await plan(ctx, version_id, only)
    #   await trace.append(ctx.writer, run_id, RescanPlanned(version_id, [t.nct_id for t in to_judge], skipped))
    #   if not to_judge: return RescanReport.nothing_to_do(...)
    #   sem = asyncio.Semaphore(concurrency)
    #   async def one(t): async with sem: return await judge_trial(ctx, t, await trials.criteria(ctx, t.nct_id, for_agent=True), profile, run_id, max_attempts)
    #   results = await asyncio.gather(*(one(t) for t in to_judge), return_exceptions=True)
    #   failed = [(t.nct_id, str(e)) for t, e in zip(to_judge, results) if isinstance(e, Exception)]
    #   await trace.append(ctx.writer, run_id, RescanFinished(judged, failed))
    #   return RescanReport(...)
    """
    raise NotImplementedError
