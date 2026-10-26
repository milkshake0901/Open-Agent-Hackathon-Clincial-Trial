"""Answer one question from the regions of a parsed letter, and keep the box each sentence came from.

The model sees the region id and the words. It does not see the page image, and it cannot invent a
citation: a span id that is not one of this patient's regions is dropped. The quote shown later is
the stored text of that region, not a sentence the model wrote.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from app.config import REPO_ROOT
from app.ctx import Ctx
from app.extraction import render_page
from app.llm import Lane, complete
from app.record.types import PatientId

SYSTEM = """You answer one question about a patient using only the letter regions listed in the user message.
Each region has an id. Those words are the only evidence you may use.
"The last ten days" means the ten calendar days ending on the as-of date, including that date.
Chemotherapy means cytotoxic drugs named in the letter (taxotere, docetaxel, cabazitaxel, carboplatin and the like). Hormone therapy, radiotherapy and radioligand therapy are not chemotherapy unless the letter itself calls them chemotherapy.
Count from the latest chemotherapy date you can read to the as-of date. If that date falls outside the ten-day window, or the letter ends before the window, the answer is no.
Cite only the ids of regions whose words you used. Do not invent a date, a drug, or an id.
answer is yes, no, or unknown. reasoning is at most two sentences and names the dates you compared. span_ids lists the region ids."""


class _ModelAnswer(BaseModel):
    answer: Literal["yes", "no", "unknown"]
    reasoning: str
    span_ids: list[str] = Field(default_factory=list)


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


@dataclass(frozen=True)
class GroundedCitation:
    span_id: str
    document_hash: str
    filename: str
    page: int
    quote: str
    x0: float
    y0: float
    x1: float
    y1: float


@dataclass(frozen=True)
class GroundedAnswer:
    answer: Literal["yes", "no", "unknown"]
    reasoning: str
    as_of: date
    patient_label: str
    document_hash: str
    filename: str
    page_count: int
    citations: tuple[GroundedCitation, ...]


def regions_text(spans: list[dict]) -> str:
    """The letter as the model sees it: one region per line, id then words. Headers that repeat are kept once."""
    lines: list[str] = []
    seen: set[str] = set()
    for span in spans:
        text = " ".join(str(span["text"]).split())
        if span["kind"] in ("Page-footer",) or not text:
            continue
        key = text.casefold()
        if span["kind"] == "Caption" and key in seen:
            continue
        seen.add(key)
        lines.append(f"[{span['id']}] {text}")
    return "\n".join(lines)


def question_prompt(question: str, as_of: date, spans: list[dict]) -> str:
    return f"As of {as_of.isoformat()}.\nQuestion: {question.strip()}\n\nRegions:\n{regions_text(spans)}"


def citations_for(span_ids: list[str], spans: list[dict]) -> tuple[GroundedCitation, ...]:
    """Keep cited ids that belong to this letter, in the model's order, once each. The quote is the region's text."""
    by_id = {span["id"]: span for span in spans}
    chosen: list[GroundedCitation] = []
    seen: set[str] = set()
    for span_id in span_ids:
        span = by_id.get(span_id)
        if span is None or span_id in seen:
            continue
        seen.add(span_id)
        chosen.append(GroundedCitation(
            span_id=span_id, document_hash=span["document_hash"], filename=span["filename"],
            page=int(span["page"]), quote=str(span["text"]).strip(),
            x0=float(span["x0"]), y0=float(span["y0"]), x1=float(span["x1"]), y1=float(span["y1"]),
        ))
    return tuple(chosen)


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


async def ask(ctx: Ctx, patient_id: PatientId, question: str) -> GroundedAnswer:
    """One question, answered from this patient's parsed letter. Raises NotFound when there is no letter."""
    from app.record import NotFound, repo

    await _patient(ctx, patient_id)
    spans = await repo.spans_for_patient(ctx.ui_reader, patient_id)
    if not spans:
        raise NotFound(f"patient {patient_id} has no parsed letter")
    as_of = ctx.now().date()
    completion = await complete(ctx, Lane.DEEP, system=SYSTEM, user=question_prompt(question, as_of, spans),
                                out=_ModelAnswer, run_id=None)
    first = spans[0]
    return GroundedAnswer(
        answer=completion.value.answer, reasoning=completion.value.reasoning.strip(), as_of=as_of,
        patient_label=first["patient_label"], document_hash=first["document_hash"], filename=first["filename"],
        page_count=int(first["page_count"]), citations=citations_for(completion.value.span_ids, spans),
    )


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
