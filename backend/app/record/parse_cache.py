"""A parsed letter, saved by the bytes of the PDF, so the same file is not sent to Nemotron Parse again.

The file is the de-identified read: pages and Regions. It lives under data/parse_cache, which is gitignored,
next to the raw PDFs. Tests do not read or write it.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from app.config import REPO_ROOT
from app.extraction import ExtractedBlock, ExtractedDocument, ExtractedPage
from app.record.types import Document

CACHE = REPO_ROOT / "data" / "parse_cache"


def enabled() -> bool:
    return "PYTEST_CURRENT_TEST" not in os.environ


def key_for(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def load(content: bytes, directory: Path | None = None) -> tuple[ExtractedDocument, str] | None:
    path = (CACHE if directory is None else directory) / f"{key_for(content)}.json"
    if not path.is_file():
        return None
    saved = json.loads(path.read_text())
    pages = tuple(
        ExtractedPage(number=page["number"], text=page["text"], blocks=tuple(
            ExtractedBlock(ordinal=block["ordinal"], kind=block["kind"], text=block["text"],
                           xmin=block["xmin"], ymin=block["ymin"], xmax=block["xmax"], ymax=block["ymax"])
            for block in page["blocks"]))
        for page in saved["pages"])
    return ExtractedDocument(pages), saved["filename"]


def save(content: bytes, parsed: ExtractedDocument, filename: str, directory: Path | None = None) -> None:
    directory = CACHE if directory is None else directory
    directory.mkdir(parents=True, exist_ok=True)
    payload = {
        "filename": filename,
        "pages": [
            {"number": page.number, "text": page.text, "blocks": [
                {"ordinal": block.ordinal, "kind": block.kind, "text": block.text,
                 "xmin": block.xmin, "ymin": block.ymin, "xmax": block.xmax, "ymax": block.ymax}
                for block in page.blocks]}
            for page in parsed.pages],
    }
    (directory / f"{key_for(content)}.json").write_text(json.dumps(payload))


def from_document(doc: Document) -> tuple[ExtractedDocument, str]:
    """The Regions already stored for a letter, in the shape a fresh parse would have after de-identification."""
    by_page: dict[int, list] = {}
    for region in doc.regions:
        by_page.setdefault(region.page, []).append(region)
    pages = tuple(
        ExtractedPage(number=page.number, text=page.text, blocks=tuple(
            ExtractedBlock(ordinal=region.ordinal, kind=region.kind, text=region.text,
                           xmin=region.x0, ymin=region.y0, xmax=region.x1, ymax=region.y1)
            for region in sorted(by_page.get(page.number, []), key=lambda region: region.ordinal)))
        for page in doc.pages)
    return ExtractedDocument(pages), doc.filename
