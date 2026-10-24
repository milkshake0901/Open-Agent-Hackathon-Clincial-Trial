"""app/record/loop.py — the Intake⇄Critic loop as a bounded state machine.

Transitions are a closed set; the attempt bound is a field; exhaustion is a transition.
Every step is appended to the run's trace, and a parked run (AwaitingPatient) is rehydrated
from those trace events on confirm(). Accepted Facts are committed through the World Model.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Awaitable, Callable

from app.ctx import Ctx
from app.record import critic, intake, repo
from app.worldmodel import timeline
from app.record.types import (
    AwaitingPatient, Committed, Conflict, Document, DraftFact, Finding, IngestOutcome,
    ProfileVersion, Rejected, Resolution,
)
from app import trace
from app.trace.events import (
    CriticReviewed, IngestRetried, IngestStarted, IntakeDrafted, ProfileCommitted, RunAwaitingPatient, RunRejected,
)
from app.trace.state import IngestRunState


# ---- step results (closed set) ---------------------------------------------

@dataclass(frozen=True)
class Retry:
    feedback: tuple[Finding, ...]      # only retryable findings; fed back to Intake

@dataclass(frozen=True)
class Escalate:
    conflicts: tuple[Conflict, ...]
    accepted_drafts: tuple[DraftFact, ...]   # drafts with no findings; kept for commit after confirm

@dataclass(frozen=True)
class Accept:
    drafts: tuple[DraftFact, ...]

@dataclass(frozen=True)
class Exhausted:
    last_findings: tuple[Finding, ...]

Step = Retry | Escalate | Accept | Exhausted

# One drafting attempt: (ctx, doc, feedback, run_id) -> drafts. intake.extract is the default (model, FAST lane);
# a questionnaire's structured answers use structured_drafter (code, no model).
Drafter = Callable[[Ctx, Document, tuple[Finding, ...], trace.RunId], Awaitable[tuple[DraftFact, ...]]]


def structured_drafter(drafts: tuple[DraftFact, ...]) -> Drafter:
    """Drafts already made in code (structured questionnaire answers). Traced like an Intake attempt."""
    async def draft(ctx: Ctx, doc: Document, feedback: tuple[Finding, ...], run_id: trace.RunId):
        await trace.append(ctx.writer, run_id, IntakeDrafted(
            actor="questionnaire", attempt=1 + bool(feedback), drafts=[asdict(d) for d in drafts],
            model_answered="none: structured answers"))
        return drafts
    return draft


def decide(findings: tuple[Finding, ...], drafts: tuple[DraftFact, ...], attempt: int, max_attempts: int,
           current: ProfileVersion | None) -> Step:
    """PURE. The whole loop policy in one function; table-tested.

    # TODO pseudocode
    #   conflicts = [f for f in findings if f.severity == "conflict"]
    #   retryable = [f for f in findings if f.severity == "retryable"]
    #   if conflicts:  -> Escalate(conflicts→Conflict objects, accepted_drafts = drafts without any finding)
    #        (conflicts are never retried: re-reading the Document cannot change what it says)
    #   elif retryable and attempt < max_attempts: -> Retry(retryable)
    #   elif retryable:  -> Exhausted(retryable)      # bound reached
    #   elif not drafts: -> Exhausted(())             # intake found nothing twice
    #   else: -> Accept(drafts)
    """
    conflicts = tuple(f for f in findings if f.severity == "conflict")
    retryable = tuple(f for f in findings if f.severity == "retryable")
    if conflicts:
        flagged = {f.draft_index for f in findings}
        return Escalate(
            conflicts=tuple(Conflict(id=f"conflict:{n}:{f.draft_index}", draft=drafts[f.draft_index], accepted=None,
                                     message=f.message) for n, f in enumerate(conflicts)),
            accepted_drafts=tuple(d for i, d in enumerate(drafts) if i not in flagged))
    if retryable:
        return Retry(retryable) if attempt < max_attempts else Exhausted(retryable)
    if not drafts:
        return Exhausted(())
    return Accept(drafts)


async def run_ingest(ctx: Ctx, doc: Document, run_id: trace.RunId, max_attempts: int, *,
                     drafter: Drafter | None = None) -> IngestOutcome:
    """Drive the loop. One place; reads like the state machine it is.

    # TODO pseudocode
    #   current = await repo.current_version(ctx.agent_reader, doc.patient_id)   # via Zetaris (ADR 0001)
    #   await trace.append(ctx.writer, run_id, IngestStarted(document_hash=doc.hash, pages=len(doc.pages)))
    #   feedback = ()
    #   for attempt in range(1, max_attempts + 1):
    #       drafts = await intake.extract(ctx, doc, feedback, run_id)        # LLM fast lane; emits IntakeDrafted
    #       findings = critic.review(drafts, doc, current)                    # PURE
    #       await trace.append(ctx.writer, run_id, CriticReviewed(attempt, findings))
    #       match decide(findings, drafts, attempt, max_attempts, current):
    #           case Accept(ds):      return await commit(ctx, doc, ds, run_id)
    #           case Escalate(cs, ok): await trace.append(..., RunAwaitingPatient(cs, ok)); return AwaitingPatient(run_id, cs)
    #           case Retry(fb):       await trace.append(..., IngestRetried(attempt, fb)); feedback = fb
    #           case Exhausted(fs):   await trace.append(..., RunRejected(reason)); return Rejected(run_id, reason)
    #   unreachable: decide() returns a terminal step on attempt == max_attempts
    """
    drafter = drafter or intake.extract
    current = await repo.current_version(ctx.agent_reader, doc.patient_id)
    await trace.append(ctx.writer, run_id, IngestStarted(actor="record", document_hash=doc.hash, pages=len(doc.pages)))
    feedback: tuple[Finding, ...] = ()
    for attempt in range(1, max_attempts + 1):
        drafts = await drafter(ctx, doc, feedback, run_id)
        findings = critic.review(drafts, doc, current)
        await trace.append(ctx.writer, run_id, CriticReviewed(actor="critic", attempt=attempt,
                                                              findings=[asdict(f) for f in findings]))
        match decide(findings, drafts, attempt, max_attempts, current):
            case Accept(drafts=ds):
                return await commit(ctx, doc, ds, run_id)
            case Escalate(conflicts=cs, accepted_drafts=ok):
                await trace.append(ctx.writer, run_id, RunAwaitingPatient(
                    actor="critic", conflicts=[asdict(c) for c in cs], accepted_drafts=[asdict(d) for d in ok]))
                return AwaitingPatient(run_id, cs)
            case Retry(feedback=fb):
                await trace.append(ctx.writer, run_id, IngestRetried(actor="critic", attempt=attempt,
                                                                     feedback=[f.message for f in fb]))
                feedback = fb
            case Exhausted(last_findings=fs):
                reason = "; ".join(f.message for f in fs) or "no Facts found in the document"
                await trace.append(ctx.writer, run_id, RunRejected(actor="record", reason=reason))
                return Rejected(run_id, reason)
    raise AssertionError("decide() returns a terminal step on the last attempt")


async def resume_after_confirm(ctx: Ctx, run_id: trace.RunId, resolutions: list[Resolution], ) -> IngestOutcome:
    """Rehydrate IngestRunState from the run log, apply resolutions, commit or stay parked.

    # TODO pseudocode
    #   state: IngestRunState = await trace.project_ingest(ctx.ui_reader, run_id)
    #   assert state.phase == "awaiting_patient"
    #   remaining = state.conflicts minus resolved ids
    #   chosen drafts = state.accepted_drafts + [c.draft for c in resolved if choice == "accept_draft"]
    #   if remaining: append RunAwaitingPatient(remaining, chosen); return AwaitingPatient
    #   return await commit(ctx, doc, chosen, run_id)
    """
    raise NotImplementedError


async def commit(ctx: Ctx, doc: Document, drafts: tuple[DraftFact, ...], run_id: trace.RunId) -> Committed:
    """timeline.commit_profile_version(ctx.wm, ...): assert_fact per draft + snapshot, each appended
    with its projection rows in one transaction (World Model is the only writer, ADR 0001), then
    append ProfileCommitted to the trace.

    Idempotent: fact ids are content-derived and the snapshot is keyed by document hash, so a
    retry after a crash returns the existing version and only the missing trace event is appended.
    """
    version = await timeline.commit_profile_version(ctx.wm, doc.patient_id, doc, drafts, run_id)
    await trace.append(ctx.writer, run_id, ProfileCommitted(actor="record", profile_version_id=version.id,
                                                            version_number=version.number, facts_added=len(drafts)))
    return Committed(run_id, version)
