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
from app import record, trace, trials
from app.record import ProfileVersion, ProfileVersionId
from app.trials import Criterion, NctId, Trial
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
    """PURE loop policy: Approve if no rejections; Retry while attempts remain; else Exhausted."""
    if not review.rejections:
        return Approve(evaluator.approve(review.results))
    if attempt < max_attempts:
        return Retry(review.rejections)
    return Exhausted(review.results, review.rejections)


def _rejections(rs: tuple[Rejection, ...]) -> list[dict]:
    return [{"criterion_id": r.criterion_id, "reason": r.reason} for r in rs]


async def judge_trial(ctx: Ctx, trial: Trial, criteria: tuple[Criterion, ...], profile: ProfileVersion,
                      run_id: trace.RunId, max_attempts: int) -> Verdict:
    """Matcher proposes, Evaluator reviews, bounded by max_attempts. On exhaustion the unsupported claims are
    downgraded to unknown (never shipped). The Verdict is written to the World Model, then traced."""
    feedback: tuple[Rejection, ...] = ()
    downgraded = 0
    for attempt in range(1, max_attempts + 1):
        results = await matcher.propose(ctx, trial, criteria, profile, feedback, run_id, attempt)
        review = await evaluator.review(ctx, results, criteria, profile, run_id)
        match decide(review, attempt, max_attempts):
            case Approve(results=vr):
                await trace.append(ctx.writer, run_id, EvaluatorApproved(
                    actor="evaluator", nct_id=trial.nct_id, attempt=attempt, model_answered=review.model_answered))
                validated = vr
                break
            case Retry(rejections=rj):
                await trace.append(ctx.writer, run_id, EvaluatorRejected(
                    actor="evaluator", nct_id=trial.nct_id, attempt=attempt, rejections=_rejections(rj),
                    model_answered=review.model_answered))
                await trace.append(ctx.writer, run_id, MatcherRetried(actor="matcher", nct_id=trial.nct_id,
                                                                      attempt=attempt + 1))
                feedback = rj
            case Exhausted(last_results=rs, rejections=rj):
                await trace.append(ctx.writer, run_id, EvaluatorRejected(
                    actor="evaluator", nct_id=trial.nct_id, attempt=attempt, rejections=_rejections(rj),
                    model_answered=review.model_answered))
                validated = evaluator.downgrade(rs, rj, criteria, attempt)
                downgraded = len({r.criterion_id for r in rj})
    order = {c.id: c.ordinal for c in criteria}
    validated = type(validated)(sorted(validated, key=lambda r: order[r.criterion_id]))
    outcome = verdict_rules.derive_outcome(validated, criteria)
    questions, asked = verdict_rules.questions_from_unknowns(validated, criteria, trial, matcher.askable())
    v = Verdict(nct_id=trial.nct_id, profile_version_id=profile.id, eligibility_hash=trial.eligibility_hash,
                outcome=outcome, results=validated, questions=questions, run_id=run_id, attempts=attempt,
                unsupported_downgraded=downgraded, degraded=downgraded > 0, respondent_questions=asked)
    await timeline.record_verdict(ctx.wm, profile.patient_id, v)
    await trace.append(ctx.writer, run_id, TrialJudged(
        actor="matching", nct_id=trial.nct_id, outcome=outcome, attempts=attempt, unsupported_downgraded=downgraded,
        degraded=v.degraded, questions=len(questions),
        respondent_questions=len(asked)))
    return v


async def plan(ctx: Ctx, version_id: ProfileVersionId, only: set[NctId] | None,
               condition: str | None = None) -> tuple[list[Trial], list[NctId]]:
    """(to_judge, skipped). SQL: active trials LEFT JOIN verdict ON (nct, trial.eligibility_hash, version)
    WHERE verdict is null. Reads via ctx.agent_reader (Zetaris). Old-hash Verdicts are kept (ADR 0002).
    A confirmed diagnosis `condition` (#14) leaves out Trials that do not study it (neither judged nor skipped)."""
    to_judge, skipped = await repo.trials_needing_verdict(ctx.agent_reader, version_id, only)
    if condition is None:
        return to_judge, skipped
    selected = {t.nct_id for t in await trials.active_trials(ctx) if trials.studies_condition(t, condition)}
    return [t for t in to_judge if t.nct_id in selected], [n for n in skipped if n in selected]


async def condition_for(ctx: Ctx, patient_id: record.PatientId) -> str | None:
    """The patient's confirmed diagnosis term, if any (record.diagnosis)."""
    held = await record.diagnosis(ctx, patient_id)
    return held.condition if held else None


async def run_rescan(ctx: Ctx, version_id: ProfileVersionId, only: set[NctId] | None, run_id: trace.RunId,
                     max_attempts: int, concurrency: int) -> RescanReport:
    """Plan, then judge each planned Trial with bounded concurrency. A Trial that fails (model unavailable) is
    reported and left without a Verdict, so the next Re-scan picks it up."""
    profile = await record.profile_version(ctx, version_id, for_agent=True)
    to_judge, skipped = await plan(ctx, version_id, only, await condition_for(ctx, profile.patient_id))
    await trace.append(ctx.writer, run_id, RescanPlanned(
        actor="matching", profile_version_id=version_id, to_judge=[t.nct_id for t in to_judge],
        skipped_existing=list(skipped)))
    if not to_judge:
        await trace.append(ctx.writer, run_id, RescanFinished(actor="matching", judged=[], failed=[]))
        return RescanReport.nothing_to_do(version_id, run_id, tuple(skipped))
    sem = asyncio.Semaphore(concurrency)

    async def one(t: Trial) -> Verdict:
        async with sem:
            return await judge_trial(ctx, t, await trials.criteria(ctx, t.nct_id, for_agent=True), profile, run_id,
                                     max_attempts)

    results = await asyncio.gather(*(one(t) for t in to_judge), return_exceptions=True)
    failed = tuple((t.nct_id, str(e)) for t, e in zip(to_judge, results) if isinstance(e, BaseException))
    judged = tuple(t.nct_id for t, e in zip(to_judge, results) if not isinstance(e, BaseException))
    await trace.append(ctx.writer, run_id, RescanFinished(actor="matching", judged=list(judged),
                                                          failed=[list(f) for f in failed]))
    return RescanReport(version_id=version_id, run_id=run_id, planned=tuple(t.nct_id for t in to_judge),
                        judged=judged, skipped_existing=tuple(skipped), failed=failed)
