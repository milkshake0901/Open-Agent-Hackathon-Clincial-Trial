"""Two letter fixtures as recorded Nemotron Parse output, and a parser that replays them.

The Region data in tests/fixtures/regions/ is invented and de-identified. It mirrors the shape of two real
documents (a narrative oncology letter, a structured MRI report), never their content. The real PDFs stay
in the gitignored raw folder.

    ctx = replace(make_ctx(pool), parser=RecordedParse(NARRATIVE_LETTER))
    POST /api/referrals with letter_pdf(NARRATIVE_LETTER)
"""
from __future__ import annotations

import json
from pathlib import Path

from app.extraction import ExtractedBlock, ExtractedDocument, ExtractedPage
from tests.pdfs import make_pdf

REGIONS = Path(__file__).resolve().parent / "regions"


def load_regions(name: str) -> ExtractedDocument:
    """A recorded document: each page's Regions in reading order, with kind, text and box."""
    recorded = json.loads((REGIONS / f"{name}.json").read_text())
    pages = []
    for page in recorded["pages"]:
        blocks = tuple(
            ExtractedBlock(ordinal, region["kind"], region["text"], *region["box"])
            for ordinal, region in enumerate(page["regions"]))
        pages.append(ExtractedPage(number=page["number"], text="\n".join(block.text for block in blocks),
                                   blocks=blocks))
    return ExtractedDocument(pages=tuple(pages))


NARRATIVE_LETTER = load_regions("narrative_letter")
"""3 pages: day/month dates (7/2/23, 23/11/23), Enantone with no testosterone value, a "Re:" identity line,
barcodes, address footers, about 40 Facts."""

STRUCTURED_REPORT = load_regions("structured_report")
"""1 page: written-out dates, "4 months ago", "No meniscal tear", a header identity block."""

NARRATIVE_LETTER_IDENTITY = ("HARLOW", "Harlow", "DESMOND", "Desmond", "P482913", "OC.9081726", "14/03/1957",
                             "943 552 7781", "18 Juniper Close", "WG7 3RN")
"""The invented patient's name, hospital number, barcode, date of birth, NHS number and home address."""

STRUCTURED_REPORT_IDENTITY = ("QUINN", "Talia", "Maree", "09 June 1991", "LKI-5520917")
"""The invented patient's name, date of birth and patient id."""


def letter_pdf(document: ExtractedDocument, marker: str = "") -> bytes:
    """A PDF with as many pages as the recording, so page images render. Its own text is a placeholder.
    A different `marker` gives different bytes, and so a different Document."""
    return make_pdf(*(f"recorded page {page.number} {marker}" for page in document.pages))


class RecordedParse:
    """Stands in for Nemotron Parse on Ctx: every read returns the recording, without a network call.
    With no recording, every read raises, the way FakeLLM does with no responder."""

    def __init__(self, document: ExtractedDocument | None = None) -> None:
        self.document = document
        self.reads: list[bytes] = []

    def read(self, content: bytes) -> ExtractedDocument:
        self.reads.append(content)
        if self.document is None:
            raise LookupError("RecordedParse has no recording; pass one to make_ctx(parser=...)")
        return self.document
