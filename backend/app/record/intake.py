"""app/record/intake.py — Intake agent: de-identified Pages (+ critic feedback) → DraftFacts. Fast lane."""
from __future__ import annotations

from pydantic import BaseModel

from app.ctx import Ctx
from app.llm import Lane, complete
from app.record.types import Document, DraftFact, Finding
from app import trace
from app.trace.events import IntakeDrafted


class _DraftFactOut(BaseModel):
    """Model output schema. Private to this file; parsed into DraftFact before leaving."""
    resource: str
    subject: str
    value: str
    unit: str | None = None
    observed_on: str | None = None     # ISO date or null; the critic flags null
    page: int
    quote: str


class _IntakeOut(BaseModel):
    facts: list[_DraftFactOut]


async def extract(ctx: Ctx, doc: Document, feedback: tuple[Finding, ...], run_id: trace.RunId) -> tuple[DraftFact, ...]:
    """One Intake attempt. Feedback from the previous attempt is rendered into the prompt as
    numbered corrections ("fact 3: quote not found on page 2; re-check page numbers").

    # TODO pseudocode
    #   prompt = render("prompts/intake.md", pages=doc.pages, feedback=feedback, doc_date=doc.uploaded_at)
    #   out = await complete(ctx, Lane.FAST, system=..., user=prompt, out=_IntakeOut, run_id=run_id)
    #   drafts = tuple(to_draft(f) for f in out.value.facts)      # parse dates; unknown resource → Observation
    #   await trace.append(ctx.writer, run_id, IntakeDrafted(attempt=len(feedback)>0..., drafts=drafts, model=out.model_answered))
    #   return drafts
    """
    raise NotImplementedError
