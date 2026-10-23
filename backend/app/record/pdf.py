"""app/record/pdf.py — Document bytes → Pages (text + tables). Page numbers are 1-based and are
what Citations point at. Tabular blood reports keep their rows so Intake can read values and units."""
from __future__ import annotations

from app.record.types import Page


def to_pages(content: bytes) -> tuple[Page, ...]:
    """# TODO: pdfplumber; extract_text() + extract_tables() per page. Raises UnreadableDocument for scans
    without a text layer (OCR is out of scope for the hackathon)."""
    raise NotImplementedError


class UnreadableDocument(Exception): ...
