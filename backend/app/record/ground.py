"""A patient's stored Regions, for the trial question to cite, and a stored page image their boxes point into.

The trial question (matching.ask_trial) sees each Region's id and words, never the page image, and its citations
keep only ids that are this patient's Regions; the quote shown is the Region's stored text.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.config import REPO_ROOT
from app.ctx import Ctx
from app.extraction import render_page
from app.record.types import PatientId


@dataclass(frozen=True)
class LetterSpan:
    """One region of a parsed letter. A trial screen cites this id, and the quote is this text."""
    id: str
    document_hash: str
    filename: str
    page: int
    kind: str
    text: str
    x0: float
    y0: float
    x1: float
    y1: float


async def letter_spans(ctx: Ctx, patient_id: PatientId, *, for_agent: bool = False) -> tuple[LetterSpan, ...]:
    """The parsed regions of this patient's letters, in reading order. Raises NotFound when there is no letter.

    for_agent reads through Zetaris (ADR 0001). The page highlight reads Postgres."""
    from app.record import NotFound, repo

    await _patient(ctx, patient_id)
    reader = ctx.agent_reader if for_agent else ctx.ui_reader
    rows = await repo.spans_for_patient(reader, patient_id)
    if not rows:
        raise NotFound(f"patient {patient_id} has no parsed letter")
    return tuple(LetterSpan(
        id=row["id"], document_hash=row["document_hash"], filename=row["filename"], page=int(row["page"]),
        kind=row["kind"], text=str(row["text"]).strip(),
        x0=float(row["x0"]), y0=float(row["y0"]), x1=float(row["x1"]), y1=float(row["y1"]),
    ) for row in rows)


async def _patient(ctx: Ctx, patient_id: PatientId) -> None:
    from app.record import NotFound, repo

    if not await repo.patient_exists(ctx.ui_reader, patient_id):
        raise NotFound(f"patient {patient_id}")


def page_png(raw_documents_dir: str, document_hash: str, number: int) -> bytes:
    """The stored PDF page, rendered the same way it was parsed, so a box lines up with the words."""
    from app.record import NotFound

    base = Path(raw_documents_dir)
    if not base.is_absolute():
        base = REPO_ROOT / base
    path = base / f"{document_hash}.pdf"
    if not path.is_file():
        raise NotFound(f"document {document_hash} has no stored PDF")
    try:
        return render_page(path.read_bytes(), number)
    except ValueError as e:
        raise NotFound(str(e)) from e
