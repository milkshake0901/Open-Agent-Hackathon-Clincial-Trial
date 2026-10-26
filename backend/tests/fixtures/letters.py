"""Two letter fixtures as recorded Nemotron Parse output, and a parser that replays them.

The Region data in tests/fixtures/regions/ is invented and de-identified. It mirrors the shape of two real
documents (a narrative oncology letter, a structured MRI report), never their content. The real PDFs stay
in the gitignored raw folder.

    ctx = replace(make_ctx(pool), parser=RecordedParse(NARRATIVE_LETTER))
    POST /api/patients/{pid}/documents with letter_pdf(NARRATIVE_LETTER)

Hand-made recordings for added-Document tests: `recording(...)` per page, `letter_pdf(read, "name")` for its bytes,
and `recorded((bytes, read), ...)` as the parser replaying them.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
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


def recording(*pages: str | tuple[tuple[str, str], ...]) -> ExtractedDocument:
    """A hand-made recording, one argument per page: a string is one Text Region per non-empty line, a tuple is
    (kind, text) Regions. Each Region gets a box one line high, stacked down the page in reading order."""
    def regions(page):
        return tuple(("Text", line) for line in page.split("\n") if line.strip()) if isinstance(page, str) else page
    return ExtractedDocument(pages=tuple(
        ExtractedPage(number=n, text="\n".join(text for _, text in regions(page)),
                      blocks=tuple(ExtractedBlock(i, kind, text, 0.08, 0.05 + 0.04 * i, 0.92, 0.08 + 0.04 * i)
                                   for i, (kind, text) in enumerate(regions(page))))
        for n, page in enumerate(pages, 1)))


def letter_pdf(document: ExtractedDocument, marker: str = "") -> bytes:
    """A PDF with as many pages as the recording, so page images render. Its own text is a placeholder.
    A different `marker` gives different bytes, and so a different Document."""
    return make_pdf(*(f"recorded page {page.number} {marker}" for page in document.pages))


class RecordedParse:
    """Stands in for Nemotron Parse on Ctx: every read returns a recording, without a network call.
    Given one recording, every read returns it; given recordings by PDF bytes, each read returns the one for its
    bytes, and other bytes raise. With no recording, every read raises, the way FakeLLM does with no responder."""

    def __init__(self, document: ExtractedDocument | Mapping[bytes, ExtractedDocument] | None = None) -> None:
        self.document = document
        self.reads: list[bytes] = []

    def read(self, content: bytes) -> ExtractedDocument:
        self.reads.append(content)
        if isinstance(self.document, Mapping):
            if content not in self.document:
                raise LookupError("RecordedParse has no recording for these bytes")
            return self.document[content]
        if self.document is None:
            raise LookupError("RecordedParse has no recording; pass one to make_ctx(parser=...)")
        return self.document


def recorded(*documents: tuple[bytes, ExtractedDocument]) -> RecordedParse:
    """A parser replaying each (PDF bytes, recording) pair."""
    return RecordedParse(dict(documents))


def intake_reading(facts: list[dict]):
    """A scripted Intake model that reads a page the way a careful model would: each per-page Intake prompt lists the
    page's Regions as `[span_id] (Kind) text`, and the reply is every scripted Fact whose quote is inside one of those
    Regions, naming that Region. A Fact quoted on no Region of the page is not drafted from it."""
    import re

    marker = re.compile(r"^\[(\S+)\] \(([^)]+)\) ", re.MULTILINE)

    def regions(user: str) -> list[tuple[str, str]]:
        starts = list(marker.finditer(user))
        return [(m.group(1), user[m.end():starts[i + 1].start() if i + 1 < len(starts) else len(user)])
                for i, m in enumerate(starts)]

    def squash(text: str) -> str:
        return " ".join(text.split()).lower()

    def respond(lane, system, user):
        shown = regions(user)
        drafted = []
        for fact in facts:
            span = next((span for span, text in shown if squash(fact["quote"]) in squash(text)), None)
            if span is not None:
                drafted.append({**fact, "span_id": span})
        return {"facts": drafted}
    return respond
