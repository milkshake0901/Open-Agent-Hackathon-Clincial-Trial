"""app/record/repo.py — SQL for the record module. One function per question.

Every read takes a SqlReader so the same query serves Zetaris (agents) and Postgres (UI).
Query text is ANSI; table names go through reader.table("fact") so Zetaris can qualify them.
"""
from __future__ import annotations

from app.record.types import Document, DocumentHash, Fact, FactId, PatientId, ProfileVersion, ProfileVersionId
from app.sql.reader import SqlReader
from app.sql.writer import PgWriter, Tx


async def document(reader: SqlReader, h: DocumentHash) -> Document | None:
    raise NotImplementedError

async def current_version(reader: SqlReader, patient_id: PatientId) -> ProfileVersion | None:
    """Highest number for the patient, with facts loaded."""
    raise NotImplementedError

async def version(reader: SqlReader, version_id: ProfileVersionId, *, with_facts: bool) -> ProfileVersion | None:
    raise NotImplementedError

async def versions(reader: SqlReader, patient_id: PatientId) -> list[ProfileVersion]:
    raise NotImplementedError

async def version_for_document(reader: SqlReader, h: DocumentHash) -> ProfileVersion | None:
    """Idempotency probe for ingest()."""
    raise NotImplementedError


# ---- writes (PgWriter only) ------------------------------------------------

async def insert_document(tx: Tx, doc: Document) -> None:
    """ON CONFLICT (hash) DO NOTHING."""
    raise NotImplementedError

# Facts and Profile versions are NOT inserted here: they are written only through
# app.worldmodel.timeline.commit_profile_version (World Model → projector), per ADR 0001.
