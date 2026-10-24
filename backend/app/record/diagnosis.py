"""app/record/diagnosis.py — propose a condition term for the free-text diagnosis (#14). Fast lane."""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.ctx import Ctx
from app.llm import Lane, complete

# Below this the term is not offered: the Respondent is told to check with their GP instead.
MIN_CONFIDENCE = 0.6


class _TermOut(BaseModel):
    term: str | None = None
    confidence: float = Field(ge=0, le=1)


SYSTEM = """You turn a patient's or carer's own description of a diagnosis into one standard condition term, as
ClinicalTrials.gov lists conditions ("non-small cell lung cancer", "HER2-positive breast cancer"). Answer with
JSON only: {"term": "...", "confidence": 0.0}
- term is lower case, spelled out in full (no abbreviations), and no more specific than the description supports.
- confidence is how sure you are (0 to 1) that the term names what the description means. If the description is
  not a diagnosis, or could mean several different conditions, give your best term with a low confidence, or null."""


async def propose_term(ctx: Ctx, text: str) -> tuple[str | None, float]:
    """(term, confidence); the term is None when it is missing or below MIN_CONFIDENCE. The model sees only the
    diagnosis words. Raises llm.LlmUnavailable."""
    out = (await complete(ctx, Lane.FAST, system=SYSTEM, user=f"Diagnosis, in the Respondent's words:\n{text}",
                          out=_TermOut, run_id=None)).value
    term = " ".join((out.term or "").split()) or None
    return (term if term and out.confidence >= MIN_CONFIDENCE else None), out.confidence
