"""app/trace/state.py — PURE reducers: trace events → run state (what a parked or running run looks like)."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Literal

from app.trace.events import (
    CriticReviewed, IntakeDrafted, LlmCalled, PatientResolved, ProfileCommitted, ReviewAnswered, RunAwaitingPatient,
    RunAwaitingReview, RunEvent, RunRejected,
)


@dataclass
class IngestRunState:
    phase: Literal["started", "drafting", "awaiting_patient", "awaiting_review", "committed", "rejected"] = "started"
    attempt: int = 0
    drafts: list[dict] = field(default_factory=list)
    findings: list[dict] = field(default_factory=list)
    conflicts: list[dict] = field(default_factory=list)
    accepted_drafts: list[dict] = field(default_factory=list)
    resolved: list[dict] = field(default_factory=list)     # {"conflict": <Conflict dict>, "choice": ...}, in order
    review: list[dict] = field(default_factory=list)       # Letter review: {"draft", "decision", "correction"} per draft
    withdrawn: list[str] = field(default_factory=list)     # accepted Fact ids the review's commit leaves out
    profile_version_id: str | None = None
    version_number: int | None = None
    reason: str | None = None              # why the run was rejected
    models_answered: list[str] = field(default_factory=list)


@dataclass
class TrialProgress:
    attempt: int = 0
    last_rejections: list[dict] = field(default_factory=list)
    outcome: str | None = None


@dataclass
class RescanRunState:
    phase: Literal["planned", "judging", "finished"] = "planned"
    profile_version_id: str | None = None
    trials: dict[str, TrialProgress] = field(default_factory=dict)   # nct → progress; concurrently updated
    skipped_existing: list[str] = field(default_factory=list)
    failed: list[list[str]] = field(default_factory=list)


def reduce_ingest(state: IngestRunState, ev: RunEvent) -> IngestRunState:
    """IntakeDrafted → drafts/attempt (a questionnaire drafts twice per attempt: code, then the Intake agent);
    CriticReviewed → findings; RunAwaitingPatient → phase+conflicts; RunAwaitingReview → phase+review; ReviewAnswered → that draft's decision;
    PatientResolved → move resolved conflicts (with the choice) to `resolved`;
    ProfileCommitted → committed; RunRejected → rejected; LlmCalled → models_answered. Returns a new state."""
    s = replace(state, drafts=list(state.drafts), conflicts=list(state.conflicts), resolved=list(state.resolved),
                review=[dict(r) for r in state.review], models_answered=list(state.models_answered))
    match ev:
        case IntakeDrafted(attempt=attempt, drafts=drafts):
            s.drafts = s.drafts + drafts if attempt == s.attempt else list(drafts)
            s.phase, s.attempt = "drafting", attempt
        case CriticReviewed(findings=findings):
            s.findings = list(findings)
        case RunAwaitingPatient(conflicts=conflicts, accepted_drafts=accepted):
            s.phase, s.conflicts, s.accepted_drafts = "awaiting_patient", list(conflicts), list(accepted)
        case PatientResolved(resolutions=resolutions):
            choices = {r.get("conflict_id"): r.get("choice") for r in resolutions}
            s.resolved += [{"conflict": c, "choice": choices[c.get("id")]} for c in s.conflicts if c.get("id") in choices]
            s.conflicts = [c for c in s.conflicts if c.get("id") not in choices]
        case RunAwaitingReview(drafts=drafts, withdrawn=withdrawn):
            s.phase, s.withdrawn = "awaiting_review", list(withdrawn)
            s.review = [{"draft": d, "decision": None, "correction": None} for d in drafts]
        case ReviewAnswered(index=index, decision=decision, correction=correction):
            s.review[index] = {**s.review[index], "decision": decision, "correction": correction}
        case ProfileCommitted(profile_version_id=vid, version_number=number):
            s.phase, s.profile_version_id, s.version_number = "committed", vid, number
        case RunRejected(reason=reason):
            s.phase, s.reason = "rejected", reason
        case LlmCalled(model_answered=model):
            s.models_answered.append(model)
    return s

def reduce_rescan(state: RescanRunState, ev: RunEvent) -> RescanRunState:
    """# TODO: per-nct updates are independent keys, so interleaved events from concurrent Matcher tasks never clobber."""
    raise NotImplementedError
