"""app/record/intake.py — Intake agent: de-identified Pages (+ critic feedback) → DraftFacts. Fast lane."""
from __future__ import annotations

from dataclasses import asdict

from pydantic import BaseModel

from app.ctx import Ctx
from app.llm import Lane, complete
from app.record import critic
from app.record.types import Document, DraftFact, FactResource, Finding
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
    question: str | None = None        # "Q8" on an Intake questionnaire


class _IntakeOut(BaseModel):
    facts: list[_DraftFactOut]


SYSTEM = """You are the Intake agent of a clinical-trial matching service. You read de-identified pages of one
patient Document and list the clinical Facts it states. Answer with JSON only:
{"facts": [{"resource": "...", "subject": "...", "value": "...", "unit": null, "observed_on": "YYYY-MM-DD",
            "page": 1, "quote": "...", "question": null}]}
- resource is one of: Condition, Observation, MedicationStatement, Procedure, AllergyIntolerance.
  Diagnoses and other illnesses are Condition, treatments are Procedure, medicines are MedicationStatement,
  allergies are AllergyIntolerance, anything else is Observation.
- subject is short and lower case ("breast cancer", "chemotherapy", "tamoxifen", "penicillin").
- quote is copied verbatim from the page the Fact is on; page is that page's number.
- observed_on is the date the Fact was true in the patient's life, never the upload date. If the page gives no
  date, use null.
- One Fact per statement. Do not invent Facts the pages do not state."""

QUESTIONNAIRE = """This Document is an Intake questionnaire the Respondent completed on {doc_date}. Each answer
follows its question number ("Q8."). Draft Facts only from the answers shown.
- question is the number of the question the answer belongs to, for example "Q8".
- quote is the answer text, or the part of it the Fact comes from, copied exactly.
- Rough dates are expected. For an answer that carries a date ("chemo ended around March 2025") give your best
  estimate: YYYY-MM-DD, or YYYY-MM or YYYY when only the month or year is known. For an answer about the
  present (current medicines, allergies, illnesses the patient has now) use {doc_date}."""


def _prompt(doc: Document, feedback: tuple[Finding, ...]) -> str:
    parts = [QUESTIONNAIRE.format(doc_date=doc.uploaded_at.isoformat())] if doc.is_questionnaire else []
    parts += [f"--- Page {p.number} ---\n{p.text}" for p in doc.pages]
    if feedback:
        parts.append("Your previous answer had these problems. Fix them and answer with the full list again:\n"
                     + "\n".join(f"{n}. {f.message}" for n, f in enumerate(feedback, 1)))
    return "\n\n".join(parts)


def _resource(raw: str) -> FactResource:
    try:
        return FactResource(raw)
    except ValueError:
        return FactResource.OBSERVATION


def _to_draft(f: _DraftFactOut, doc: Document) -> DraftFact:
    return DraftFact(resource=_resource(f.resource), subject=f.subject.strip().lower(), value=f.value.strip(),
                     unit=f.unit or None, observed_on=critic.observed_on(f.observed_on, doc), page=f.page,
                     quote=f.quote.strip(), question=(f.question or None) if doc.is_questionnaire else None)


async def extract(ctx: Ctx, doc: Document, feedback: tuple[Finding, ...], run_id: trace.RunId) -> tuple[DraftFact, ...]:
    """One Intake attempt. Feedback from the previous attempt is rendered into the prompt as numbered
    corrections. Unknown resources become Observation; dates are parsed by the Critic's rule (critic.observed_on),
    so a date the Critic would not accept arrives as None and is flagged MISSING_DATE."""
    out = await complete(ctx, Lane.FAST, system=SYSTEM, user=_prompt(doc, feedback), out=_IntakeOut, run_id=run_id)
    drafts = tuple(_to_draft(f, doc) for f in out.value.facts)
    await trace.append(ctx.writer, run_id, IntakeDrafted(
        actor="intake", attempt=1 + bool(feedback), drafts=[asdict(d) for d in drafts],
        model_answered=out.model_answered))
    return drafts
