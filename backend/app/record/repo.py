"""app/record/repo.py — SQL for the record module. One function per question.

Every read takes a SqlReader so the same query serves Zetaris (agents) and Postgres (UI).
Query text is ANSI; table names go through reader.table("fact") so Zetaris can qualify them.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, time, timezone
from typing import Sequence

from app.record.types import (
    DiagnosisCheck, DiagnosisCheckId, Document, DocumentHash, Fact, FactId, FactResource, Page, PatientId, ProfileVersion,
    ProfileVersionId, Region, ReturnTokenHash, SearchPreferences,
)
from app.sql.reader import SqlReader
from app.trials import ConditionLabel
from app.sql.writer import Tx


async def patient_exists(reader: SqlReader, patient_id: PatientId) -> bool:
    return bool(await reader.fetch(f"SELECT 1 FROM {reader.table('patient')} WHERE id = $1", (patient_id,)))


async def search_preferences(reader: SqlReader, patient_id: PatientId) -> SearchPreferences:
    rows = await reader.fetch(f"SELECT postcode, max_travel_km, contact, lat, lon FROM "
                              f"{reader.table('search_preference')} WHERE patient_id = $1", (patient_id,))
    r = rows[0] if rows else {}
    location = (r["lat"], r["lon"]) if r.get("lat") is not None else None
    return SearchPreferences(postcode=r.get("postcode"), max_travel_km=r.get("max_travel_km"), contact=r.get("contact"),
                             location=location)


_CHECK_COLS = "id, patient_id, text, shortlist, ticked, status"


def _json(value):
    return json.loads(value) if isinstance(value, str) else value


def _check(r: dict) -> DiagnosisCheck:
    return DiagnosisCheck(id=DiagnosisCheckId(r["id"]), patient_id=PatientId(r["patient_id"]), text=r["text"],
                          shortlist=tuple(ConditionLabel(**o) for o in _json(r["shortlist"]) or ()),
                          ticked=tuple(_json(r["ticked"]) or ()), status=r["status"])


async def diagnosis_check(reader: SqlReader, check_id: DiagnosisCheckId) -> DiagnosisCheck | None:
    rows = await reader.fetch(f"SELECT {_CHECK_COLS} FROM {reader.table('diagnosis_check')} WHERE id = $1",
                              (check_id,))
    return _check(rows[0]) if rows else None


async def settled_diagnosis_check(reader: SqlReader, patient_id: PatientId) -> DiagnosisCheck | None:
    """The latest check that settled the diagnosis (types.SETTLED)."""
    rows = await reader.fetch(
        f"SELECT {_CHECK_COLS} FROM {reader.table('diagnosis_check')} WHERE patient_id = $1 "
        "AND settled_seq IS NOT NULL ORDER BY settled_seq DESC LIMIT 1", (patient_id,))
    return _check(rows[0]) if rows else None


async def patient_for_token_hash(reader: SqlReader, token_hash: ReturnTokenHash) -> PatientId | None:
    rows = await reader.fetch(f"SELECT patient_id FROM {reader.table('return_token')} WHERE token_hash = $1",
                              (token_hash,))
    return PatientId(rows[0]["patient_id"]) if rows else None


async def document(reader: SqlReader, h: DocumentHash) -> Document | None:
    rows = await reader.fetch(
        f"SELECT hash, patient_id, filename, respondent, uploaded_at FROM {reader.table('document')} WHERE hash = $1",
        (h,))
    if not rows:
        return None
    pages = await reader.fetch(
        f"SELECT number, text, tables_json FROM {reader.table('document_page')} WHERE document_hash = $1 "
        "ORDER BY number", (h,))
    r = rows[0]
    regions = () if r["respondent"] else tuple(
        Region(s["id"], s["page"], s["ordinal"], s["kind"], s["text"], s["x0"], s["y0"], s["x1"], s["y1"])
        for s in await spans_for_document(reader, h))
    return Document(hash=DocumentHash(r["hash"]), patient_id=PatientId(r["patient_id"]), filename=r["filename"],
                    pages=tuple(Page(number=p["number"], text=p["text"], tables=_tables(p["tables_json"])) for p in pages),
                    uploaded_at=r["uploaded_at"].date(), respondent=r["respondent"], regions=regions)


def _tables(raw) -> tuple[tuple[tuple[str, ...], ...], ...]:
    rows = json.loads(raw) if isinstance(raw, str) else (raw or [])
    return tuple(tuple(tuple(row) for row in table) for table in rows)


_VERSION_COLS = "id, patient_id, number, document_hash"


async def _build(reader: SqlReader, row: dict, with_facts: bool) -> ProfileVersion:
    facts = await reader.fetch(
        f"SELECT f.id, f.document_hash, f.page, f.resource, f.subject, f.value, f.unit, f.observed_on, f.quote, "
        f"f.question, f.span_id, f.flags FROM {reader.table('profile_version_fact')} pvf "
        f"JOIN {reader.table('fact')} f ON f.id = pvf.fact_id "
        f"JOIN {reader.table('profile_version')} accepted ON accepted.document_hash = f.document_hash "
        f"WHERE pvf.profile_version_id = $1 ORDER BY accepted.number, f.page, f.id", (row["id"],))
    loaded = tuple(Fact(id=FactId(f["id"]), document_hash=DocumentHash(f["document_hash"]), page=f["page"],
                        resource=FactResource(f["resource"]), subject=f["subject"], value=f["value"], unit=f["unit"],
                        observed_on=f["observed_on"], quote=f["quote"], question=f["question"],
                        span_id=f["span_id"], flags=tuple(f["flags"] or ())) for f in facts)
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

async def latest_questionnaire(reader: SqlReader, patient_id: PatientId) -> Document | None:
    """The Intake questionnaire Document behind the patient's latest version made from one (the latest
    accepted submission), with its pages."""
    rows = await reader.fetch(
        f"SELECT d.hash FROM {reader.table('profile_version')} pv JOIN {reader.table('document')} d "
        "ON d.hash = pv.document_hash WHERE pv.patient_id = $1 AND d.respondent IS NOT NULL "
        "ORDER BY pv.number DESC LIMIT 1", (patient_id,))
    return await document(reader, DocumentHash(rows[0]["hash"])) if rows else None


async def version_for_document(reader: SqlReader, h: DocumentHash) -> ProfileVersion | None:
    """Idempotency probe for ingest()."""
    rows = await reader.fetch(f"SELECT {_VERSION_COLS} FROM {reader.table('profile_version')} "
                              "WHERE document_hash = $1", (h,))
    return await _build(reader, rows[0], False) if rows else None


# ---- writes (PgWriter only) ------------------------------------------------

async def insert_patient(tx: Tx, patient_id: PatientId, label: str) -> None:
    await tx.execute("INSERT INTO patient (id, label) VALUES ($1, $2)", (patient_id, label))


async def upsert_search_preferences(tx: Tx, patient_id: PatientId, changes: dict) -> None:
    """Sets only the given fields (SearchPreferences names); the others keep their stored values. `location` is
    stored as lat, lon."""
    changes = dict(changes)
    if "location" in changes:
        changes["lat"], changes["lon"] = changes.pop("location") or (None, None)
    cols = [c for c in ("postcode", "lat", "lon", "max_travel_km", "contact") if c in changes]
    if not cols:
        return
    params = [patient_id] + [changes[c] for c in cols]
    marks = ", ".join(f"${i + 2}" for i in range(len(cols)))
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols)
    await tx.execute(f"INSERT INTO search_preference (patient_id, {', '.join(cols)}) VALUES ($1, {marks}) "
                     f"ON CONFLICT (patient_id) DO UPDATE SET {updates}, updated_at = now()", params)


async def insert_return_token(tx: Tx, token_hash: ReturnTokenHash, patient_id: PatientId) -> bool:
    """False if the patient already has a return token (one per patient)."""
    rows = await tx.fetch("INSERT INTO return_token (token_hash, patient_id) VALUES ($1, $2) "
                          "ON CONFLICT (patient_id) DO NOTHING RETURNING patient_id", (token_hash, patient_id))
    return bool(rows)


async def insert_diagnosis_check(tx: Tx, check: DiagnosisCheck, at: datetime) -> None:
    """A settled check (DiagnosisCheck.settled) takes the next settled_seq."""
    await tx.execute(
        "INSERT INTO diagnosis_check (id, patient_id, text, shortlist, ticked, status, created_at, "
        "answered_at, settled_seq) VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, $6, $7, $8, "
        "CASE WHEN $9 THEN nextval('diagnosis_check_settled') END)",
        (check.id, check.patient_id, check.text,
         json.dumps([asdict(one) for one in check.shortlist]),
         json.dumps(list(check.ticked)), check.status, at, at if check.status != "proposed" else None, check.settled))


async def answer_diagnosis_check(tx: Tx, answered: DiagnosisCheck, at: datetime) -> bool:
    """Sets the answer (`answered.status` and its ticked labels) once: False if the check was not awaiting one. A
    settled answer takes the next settled_seq."""
    rows = await tx.fetch(
        "UPDATE diagnosis_check SET status = $2, ticked = $5::jsonb, answered_at = $3, settled_seq = CASE WHEN $4 THEN "
        "nextval('diagnosis_check_settled') END WHERE id = $1 AND status = 'proposed' RETURNING id",
        (answered.id, answered.status, at, answered.settled, json.dumps(list(answered.ticked))))
    return bool(rows)


async def insert_document(tx: Tx, doc: Document, *, uploaded_at: "datetime | None" = None) -> None:
    """ON CONFLICT (hash) DO NOTHING. Pages go in with it, in the same transaction. `uploaded_at` keeps the
    time of day (Facts are listed in upload order); without it, midnight UTC of doc.uploaded_at."""

    await tx.execute(
        "INSERT INTO document (hash, patient_id, filename, page_count, respondent, uploaded_at) "
        "VALUES ($1, $2, $3, $4, $5, $6) ON CONFLICT (hash) DO NOTHING",
        (doc.hash, doc.patient_id, doc.filename, len(doc.pages), doc.respondent,
         uploaded_at or datetime.combine(doc.uploaded_at, time(), timezone.utc)))
    for p in doc.pages:
        await tx.execute("INSERT INTO document_page (document_hash, number, text, tables_json) "
                         "VALUES ($1, $2, $3, $4::jsonb) ON CONFLICT DO NOTHING",
                         (doc.hash, p.number, p.text, json.dumps(p.tables)))


async def spans_for_patient(reader: SqlReader, patient_id: PatientId) -> list[dict]:
    """Every region parsed from this patient's letters, in reading order. The words and the box travel together."""
    return await reader.fetch(
        f"SELECT s.id, s.document_hash, s.page, s.ordinal, s.kind, s.text, s.x0, s.y0, s.x1, s.y1, "
        f"d.filename, d.page_count, p.label AS patient_label "
        f"FROM {reader.table('document_span')} s "
        f"JOIN {reader.table('document')} d ON d.hash = s.document_hash "
        f"JOIN {reader.table('patient')} p ON p.id = d.patient_id "
        f"WHERE d.patient_id = $1 ORDER BY d.uploaded_at, s.page, s.ordinal",
        (patient_id,))


async def spans_for_document(reader: SqlReader, document_hash: DocumentHash) -> list[dict]:
    """One Document's Regions in reading order, each with its box."""
    return await reader.fetch(
        f"SELECT id, document_hash, page, ordinal, kind, text, x0, y0, x1, y1 FROM {reader.table('document_span')} "
        "WHERE document_hash = $1 ORDER BY page, ordinal", (document_hash,))


async def insert_spans(tx: Tx, document_hash: str, spans: Sequence[tuple]) -> None:
    """One row per region the parse model read. A Fact's span_id points at one of these so a trial reason
    can open the box on the page. `spans` is (id, page, ordinal, kind, text, x0, y0, x1, y1)."""
    for span in spans:
        await tx.execute(
            "INSERT INTO document_span (id, document_hash, page, ordinal, kind, text, x0, y0, x1, y1) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10) ON CONFLICT (document_hash, page, ordinal) DO NOTHING",
            (span[0], document_hash, *span[1:]))

# Facts and Profile versions are NOT inserted here: they are written only through
# app.worldmodel.timeline.commit_profile_version (World Model → projector), per ADR 0001.
