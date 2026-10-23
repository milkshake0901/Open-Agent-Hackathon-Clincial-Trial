"""app/record — PATIENT RECORD module. Public surface.

Owns: Documents, Facts, Profile versions, Conflicts, and the Intake⇄Critic loop.
Hides: PDF parsing, de-identification, two prompts, conflict rules, retry policy,
Postgres transactions, Zetaris read-after-write waits.
"""
from __future__ import annotations

from app.ctx import Ctx
from app.record.types import (
    AwaitingPatient,
    Committed,
    Conflict,
    Document,
    DocumentHash,
    DraftFact,
    Fact,
    FactId,
    IngestOutcome,
    PatientId,
    ProfileVersion,
    ProfileVersionId,
    Rejected,
    Resolution,
    VersionDiff,
)
from app.trace import RunId

__all__ = [
    "register_document", "ingest", "confirm", "versions", "profile_version", "diff",
    "current_version",
    "Document", "DraftFact", "Fact", "ProfileVersion", "Conflict", "Resolution", "VersionDiff",
    "IngestOutcome", "Committed", "AwaitingPatient", "Rejected",
    "PatientId", "DocumentHash", "ProfileVersionId", "FactId",
]


async def register_document(ctx: Ctx, patient_id: PatientId, filename: str, content: bytes) -> Document:
    """Hash content, parse pages, de-identify, persist document+pages. Idempotent on hash:
    uploading the same bytes twice returns the existing Document and does not re-parse.
    De-identified page text is what Citations display; raw bytes are kept only on disk (data/raw)."""
    raise NotImplementedError


async def ingest(ctx: Ctx, document_hash: DocumentHash, *, run_id: RunId | None = None) -> IngestOutcome:
    """Run the Intake⇄Critic loop for one Document to its terminal state.

    Terminal states (exhaustive, see record.loop):
      Committed        a new ProfileVersion exists; Facts inserted in one transaction.
      AwaitingPatient  the run is parked with Conflicts the patient must resolve (record.confirm).
      Rejected         nothing acceptable after bounded attempts, or document unreadable.

    Idempotent: if a ProfileVersion for this document_hash already exists, returns
    Committed for it without calling any model. If a run for this document is already
    AwaitingPatient, returns that AwaitingPatient.
    """
    raise NotImplementedError


async def confirm(ctx: Ctx, run_id: RunId, resolutions: list[Resolution]) -> IngestOutcome:
    """Patient resolves Conflicts on a parked run. Keeps the loop's accepted draft facts,
    applies the chosen values, commits. Partial resolutions leave the run AwaitingPatient
    with the remaining Conflicts. Rejected drafts are never inserted (Facts stay append-only)."""
    raise NotImplementedError


async def versions(ctx: Ctx, patient_id: PatientId) -> list[ProfileVersion]:
    raise NotImplementedError


async def current_version(ctx: Ctx, patient_id: PatientId) -> ProfileVersion | None:
    raise NotImplementedError


async def profile_version(ctx: Ctx, version_id: ProfileVersionId, *, for_agent: bool = False) -> ProfileVersion:
    """Load a version with its Facts. for_agent=True reads via ctx.agent_reader (Zetaris, ADR 0001)
    and waits (bounded) until the version is visible there; the HTTP shell uses the default."""
    raise NotImplementedError


async def diff(ctx: Ctx, from_version: ProfileVersionId, to_version: ProfileVersionId) -> VersionDiff:
    """Facts added between two versions and subjects whose current value changed. Pure over two loads."""
    raise NotImplementedError
