"""Store a parsed referral. The boxes belong with the document, next to its pages.

A Fact cites span_id. That id is the document, the page, and the box, so a trial reason
can open the words on the page they were read from.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.extraction import ExtractedDocument
from app.record.repo import insert_document, insert_spans
from app.record.storage import document_hash, filename
from app.record.types import Document, Page, PatientId
from app.sql.writer import PgWriter


async def save_referral(writer: PgWriter, *, patient_id: str, label: str, filename_raw: str,
                        content: bytes, parsed: ExtractedDocument, uploaded_at: datetime | None = None) -> str:
    """Idempotent on the document hash. Returns that hash."""
    patient = PatientId(patient_id)
    digest = document_hash(patient, content)
    now = uploaded_at or datetime.now(timezone.utc)
    pages = tuple(Page(number=page.number, text=page.text) for page in parsed.pages)
    doc = Document(hash=digest, patient_id=patient, filename=filename(filename_raw), pages=pages,
                   uploaded_at=now.date())
    spans = [
        (block.span_id(digest, page.number), page.number, block.ordinal, block.kind, block.text,
         block.xmin, block.ymin, block.xmax, block.ymax)
        for page in parsed.pages
        for block in page.blocks
    ]
    async with writer.transaction() as tx:
        await tx.execute(
            "INSERT INTO patient (id, label) VALUES ($1, $2) ON CONFLICT (id) DO NOTHING",
            (patient_id, label))
        await insert_document(tx, doc, uploaded_at=now)
        await insert_spans(tx, digest, spans)
    return str(digest)
