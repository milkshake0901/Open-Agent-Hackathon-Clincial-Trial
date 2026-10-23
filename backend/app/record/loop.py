"""app/record/loop.py — the Intake⇄Critic loop as a bounded state machine.

Transitions are a closed set; the attempt bound is a field; exhaustion is a transition.
Every step is appended to the run's trace, and a parked run (AwaitingPatient) is rehydrated
from those trace events on confirm(). Accepted Facts are committed through the World Model.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.ctx import Ctx
from app.record import critic, intake, repo
from app.worldmodel import timeline
from app.record.types import (
    AwaitingPatient, Committed, Conflict, Document, DraftFact, Finding, IngestOutcome,
    ProfileVersion, Rejected, Resolution,
)
from app import trace
from app.trace.events import (
    CriticReviewed, IngestRetried, IngestStarted, ProfileCommitted, RunAwaitingPatient, RunRejected,
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
    raise NotImplementedError


async def run_ingest(ctx: Ctx, doc: Document, run_id: trace.RunId, max_attempts: int) -> IngestOutcome:
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
    raise NotImplementedError


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
    raise NotImplementedError
