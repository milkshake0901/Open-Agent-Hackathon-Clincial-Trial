"""app/record/repo.py — SQL for the record module. One function per question.

Every read takes a SqlReader so the same query serves Zetaris (agents) and Postgres (UI).
Query text is ANSI; table names go through reader.table("fact") so Zetaris can qualify them.
"""
from __future__ import annotations

from datetime import datetime, time, timezone

from app.record.types import (
    Document, DocumentHash, Fact, FactId, FactResource, Page, PatientId, ProfileVersion, ProfileVersionId,
)
from app.sql.reader import SqlReader
from app.sql.writer import PgWriter, Tx


async def patient_exists(reader: SqlReader, patient_id: PatientId) -> bool:
    return bool(await reader.fetch(f"SELECT 1 FROM {reader.table('patient')} WHERE id = $1", (patient_id,)))


async def document(reader: SqlReader, h: DocumentHash) -> Document | None:
    rows = await reader.fetch(
        f"SELECT hash, patient_id, filename, respondent, uploaded_at FROM {reader.table('document')} WHERE hash = $1",
        (h,))
    if not rows:
        return None
    pages = await reader.fetch(
        f"SELECT number, text FROM {reader.table('document_page')} WHERE document_hash = $1 ORDER BY number", (h,))
    r = rows[0]
    return Document(hash=DocumentHash(r["hash"]), patient_id=PatientId(r["patient_id"]), filename=r["filename"],
                    pages=tuple(Page(number=p["number"], text=p["text"]) for p in pages),
                    uploaded_at=r["uploaded_at"].date(), respondent=r["respondent"])


_VERSION_COLS = "id, patient_id, number, document_hash"


async def _build(reader: SqlReader, row: dict, with_facts: bool) -> ProfileVersion:
    facts = await reader.fetch(
        f"SELECT f.id, f.document_hash, f.page, f.resource, f.subject, f.value, f.unit, f.observed_on, f.quote, "
        f"f.question FROM {reader.table('profile_version_fact')} pvf "
        f"JOIN {reader.table('fact')} f ON f.id = pvf.fact_id "
        f"JOIN {reader.table('document')} d ON d.hash = f.document_hash "
        f"WHERE pvf.profile_version_id = $1 ORDER BY d.uploaded_at, f.page, f.id", (row["id"],))
    loaded = tuple(Fact(id=FactId(f["id"]), document_hash=DocumentHash(f["document_hash"]), page=f["page"],
                        resource=FactResource(f["resource"]), subject=f["subject"], value=f["value"], unit=f["unit"],
                        observed_on=f["observed_on"], quote=f["quote"], question=f["question"]) for f in facts)
    return ProfileVersion(id=ProfileVersionId(row["id"]), patient_id=PatientId(row["patient_id"]),
                          number=row["number"], document_hash=DocumentHash(row["document_hash"]),
                          fact_ids=frozenset(f.id for f in loaded), facts=loaded if with_facts else ())


async def current_version(reader: SqlReader, patient_id: PatientId) -> ProfileVersion | None:
    """Highest number for the patient, with facts loaded."""
    rows = await reader.fetch(f"SELECT {_VERSION_COLS} FROM {reader.table('profile_version')} WHERE patient_id = $1 "
                              "ORDER BY number DESC LIMIT 1", (patient_id,))
    return await _build(reader, rows[0], True) if rows else None


async def version(reader: SqlReader, version_id: ProfileVersionId, *, with_facts: bool) -> ProfileVersion | None:
    rows = await reader.fetch(f"SELECT {_VERSION_COLS} FROM {reader.table('profile_version')} WHERE id = $1",
                              (version_id,))
    return await _build(reader, rows[0], with_facts) if rows else None

async def versions(reader: SqlReader, patient_id: PatientId) -> list[ProfileVersion]:
    raise NotImplementedError

async def version_for_document(reader: SqlReader, h: DocumentHash) -> ProfileVersion | None:
    """Idempotency probe for ingest()."""
    rows = await reader.fetch(f"SELECT {_VERSION_COLS} FROM {reader.table('profile_version')} "
                              "WHERE document_hash = $1", (h,))
    return await _build(reader, rows[0], False) if rows else None


# ---- writes (PgWriter only) ------------------------------------------------

async def insert_patient(tx: Tx, patient_id: PatientId, label: str) -> None:
    await tx.execute("INSERT INTO patient (id, label) VALUES ($1, $2)", (patient_id, label))


async def insert_document(tx: Tx, doc: Document, *, uploaded_at: "datetime | None" = None) -> None:
    """ON CONFLICT (hash) DO NOTHING. Pages go in with it, in the same transaction. `uploaded_at` keeps the
    time of day (Facts are listed in upload order); without it, midnight UTC of doc.uploaded_at."""

    await tx.execute(
        "INSERT INTO document (hash, patient_id, filename, page_count, respondent, uploaded_at) "
        "VALUES ($1, $2, $3, $4, $5, $6) ON CONFLICT (hash) DO NOTHING",
        (doc.hash, doc.patient_id, doc.filename, len(doc.pages), doc.respondent,
         uploaded_at or datetime.combine(doc.uploaded_at, time(), timezone.utc)))
    for p in doc.pages:
        await tx.execute("INSERT INTO document_page (document_hash, number, text) VALUES ($1, $2, $3) "
                         "ON CONFLICT DO NOTHING", (doc.hash, p.number, p.text))

# Facts and Profile versions are NOT inserted here: they are written only through
# app.worldmodel.timeline.commit_profile_version (World Model → projector), per ADR 0001.
