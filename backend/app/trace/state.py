"""app/trace/state.py — PURE reducers: trace events → run state (what a parked or running run looks like)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.trace.events import RunEvent


@dataclass
class IngestRunState:
    phase: Literal["started", "drafting", "awaiting_patient", "committed", "rejected"] = "started"
    attempt: int = 0
    drafts: list[dict] = field(default_factory=list)
    findings: list[dict] = field(default_factory=list)
    conflicts: list[dict] = field(default_factory=list)
    accepted_drafts: list[dict] = field(default_factory=list)
    profile_version_id: str | None = None
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
    """# TODO: match ev: IntakeDrafted → drafts/attempt; CriticReviewed → findings; RunAwaitingPatient → phase+conflicts;
    PatientResolved → remove resolved; ProfileCommitted → committed; RunRejected → rejected; LlmCalled → models_answered."""
    raise NotImplementedError

def reduce_rescan(state: RescanRunState, ev: RunEvent) -> RescanRunState:
    """# TODO: per-nct updates are independent keys, so interleaved events from concurrent Matcher tasks never clobber."""
    raise NotImplementedError
