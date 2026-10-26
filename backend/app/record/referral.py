"""Store a parsed referral. The boxes belong with the document, next to its pages.

A Fact cites span_id. That id is the document, the page, and the box, so a trial reason
can open the words on the page they were read from.

Every Region's text, every page's text and the filename are de-identified together before they are stored (#53),
so nothing read from Postgres or through Zetaris, and no prompt built from it, carries the patient's identity.
Boxes are kept exactly as read.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from app.extraction import ExtractedDocument, ExtractedPage
from app.record.deidentify import deidentify_document
from app.record.repo import insert_document, insert_spans
from app.record.storage import document_hash, filename
from app.record.types import Document, Page, PatientId
from app.sql.writer import PgWriter


def deidentify_parsed(parsed: ExtractedDocument, filename_raw: str) -> tuple[ExtractedDocument, str]:
    """The parsed letter and its filename with identifiers replaced, in one pass over the whole Document."""
    blocks = [block for page in parsed.pages for block in page.blocks]
    done = deidentify_document(tuple(Page(number=page.number, text=page.text) for page in parsed.pages),
                               tuple(block.text for block in blocks), filename=filename(filename_raw))
    texts = iter(done.regions)
    pages = tuple(ExtractedPage(number=page.number, text=clean.text, reasoning="",
                                blocks=tuple(replace(block, text=next(texts)) for block in page.blocks))
                  for page, clean in zip(parsed.pages, done.pages))
    return ExtractedDocument(pages=pages), done.filename


async def save_referral(writer: PgWriter, *, patient_id: str, label: str, filename_raw: str,
                        content: bytes, parsed: ExtractedDocument, uploaded_at: datetime | None = None) -> str:
    """Idempotent on the document hash. Returns that hash."""
    parsed, safe_filename = deidentify_parsed(parsed, filename_raw)
    patient = PatientId(patient_id)
    digest = document_hash(patient, content)
    now = uploaded_at or datetime.now(timezone.utc)
    pages = tuple(Page(number=page.number, text=page.text) for page in parsed.pages)
    doc = Document(hash=digest, patient_id=patient, filename=safe_filename, pages=pages,
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
