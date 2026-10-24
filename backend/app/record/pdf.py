"""app/record/pdf.py — Document bytes → Pages (text + tables). Page numbers are 1-based and are
what Citations point at. Tabular blood reports keep their rows so Intake can read values and units."""
from __future__ import annotations

import io
import logging

import pdfplumber

from app.record.types import Page

logging.getLogger("pdfminer").setLevel(logging.ERROR)


class UnreadableDocument(Exception):
    """Not a PDF, or a PDF with no text layer (a scan: OCR is out of scope for the hackathon)."""


def to_pages(content: bytes) -> tuple[Page, ...]:
    """extract_text() + extract_tables() per page. Raises UnreadableDocument for anything that is not a PDF and
    for scans without a text layer."""
    if not content.startswith(b"%PDF"):
        raise UnreadableDocument("the file is not a PDF")
    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            pages = tuple(
                Page(number=n, text=(p.extract_text() or "").strip(),
                     tables=tuple(tuple(tuple(cell or "" for cell in row) for row in table)
                                  for table in p.extract_tables()))
                for n, p in enumerate(pdf.pages, 1))
    except Exception as e:   # pdfminer raises a zoo of syntax errors on damaged files
        raise UnreadableDocument(f"the PDF could not be read ({type(e).__name__})") from e
    if not any(p.text for p in pages):
        raise UnreadableDocument("the PDF has no text layer (a scan?); only text PDFs can be read for now")
    return pages
