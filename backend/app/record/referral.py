"""Read an uploaded PDF into pages of Regions and store them. The boxes belong with the document, next to its pages.

Every PDF, whether added as a Document or uploaded as a letter, is read the same way (#45): the Parser on Ctx reads
it page by page, and every Region's text, every page's text and the filename are de-identified together, in one pass
over the whole Document, before anything is stored (#53). So nothing read from Postgres or through Zetaris, and no
prompt built from it, carries the patient's identity. Boxes are kept exactly as read.

A Fact cites span_id. That id is the document, the page, and the box, so a trial reason
can open the words on the page they were read from.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from app.extraction import ExtractedDocument, ExtractedPage, Parser
from app.record.deidentify import deidentify_document
from app.record.pdf import UnreadableDocument
from app.record.repo import insert_document, insert_spans
from app.record.storage import document_hash, filename
from app.record.types import Document, DocumentHash, Page, PatientId
from app.sql.writer import PgWriter, Tx

# Kinds that repeat on every page (letterheads, footers): a PDF whose Regions are only these has nothing to read.
_FURNITURE = {"Page-header", "Page-footer"}


def deidentify_parsed(parsed: ExtractedDocument, filename_raw: str) -> tuple[ExtractedDocument, str]:
    """The parsed PDF and its filename with identifiers replaced, in one pass over the whole Document."""
    blocks = [block for page in parsed.pages for block in page.blocks]
    done = deidentify_document(tuple(Page(number=page.number, text=page.text) for page in parsed.pages),
                               tuple(block.text for block in blocks), filename=filename(filename_raw))
    texts = iter(done.regions)
    pages = tuple(ExtractedPage(number=page.number, text=clean.text, reasoning="",
                                blocks=tuple(replace(block, text=next(texts)) for block in page.blocks))
                  for page, clean in zip(parsed.pages, done.pages))
    return ExtractedDocument(pages=pages), done.filename


def read_pdf(parser: Parser, filename_raw: str, content: bytes) -> tuple[ExtractedDocument, str]:
    """Read a PDF through the Parser and de-identify it: its pages of Regions and its filename, ready to store.
    Synchronous, one parse call per page: run it in a thread. Raises UnreadableDocument for an empty file, anything
    that is not a PDF, a PDF that cannot be rendered, and a PDF in which the parse finds no readable text (a blank
    page, or a scan too faint to read): only page headers and footers, or nothing."""
    if not content:
        raise UnreadableDocument("the file is empty")
    if not content.startswith(b"%PDF"):
        raise UnreadableDocument("the file is not a PDF")
    try:
        parsed = parser.read(content)
    except ValueError as e:   # pypdfium2 cannot render a damaged file
        raise UnreadableDocument(f"the PDF could not be read ({e})") from e
    if not any(block.text.strip() and block.kind not in _FURNITURE for page in parsed.pages for block in page.blocks):
        raise UnreadableDocument("no readable text was found in the PDF (a blank page, or a scan too faint to read?)")
    return deidentify_parsed(parsed, filename_raw)


def as_document(patient_id: PatientId, content: bytes, safe_filename: str, parsed: ExtractedDocument,
                uploaded_at: datetime) -> Document:
    """The Document a read PDF becomes: its page texts, keyed by the patient and the bytes."""
    return Document(hash=document_hash(patient_id, content), patient_id=patient_id, filename=safe_filename,
                    pages=tuple(Page(number=page.number, text=page.text) for page in parsed.pages),
                    uploaded_at=uploaded_at.date())


async def store_document(tx: Tx, doc: Document, parsed: ExtractedDocument, uploaded_at: datetime) -> None:
    """The Document, its pages and one row per Region with its box, in the caller's transaction."""
    await insert_document(tx, doc, uploaded_at=uploaded_at)
    await insert_spans(tx, doc.hash, [
        (block.span_id(doc.hash, page.number), page.number, block.ordinal, block.kind, block.text,
         block.xmin, block.ymin, block.xmax, block.ymax)
        for page in parsed.pages
        for block in page.blocks
    ])


async def save_referral(writer: PgWriter, *, patient_id: str, label: str, filename_raw: str,
                        content: bytes, parsed: ExtractedDocument, uploaded_at: datetime | None = None) -> str:
    """Store an already-parsed letter for `patient_id`, creating that patient if needed (scripts/load_referral.py).
    De-identifies it first. Idempotent on the document hash. Returns that hash."""
    parsed, safe_filename = deidentify_parsed(parsed, filename_raw)
    now = uploaded_at or datetime.now(timezone.utc)
    doc = as_document(PatientId(patient_id), content, safe_filename, parsed, now)
    async with writer.transaction() as tx:
        await tx.execute(
            "INSERT INTO patient (id, label) VALUES ($1, $2) ON CONFLICT (id) DO NOTHING",
            (patient_id, label))
        await store_document(tx, doc, parsed, now)
    return str(DocumentHash(doc.hash))
