"""app/record/intake.py — Intake agent: de-identified Pages (+ critic feedback) → DraftFacts. Fast lane.

A clinical Document read into Regions is drafted one page at a time (extract_page), from that page's citable Regions
(types.INTAKE_KINDS), with one prompt for every kind of document; each draft names the Region it quotes, and its page
and span_id are that Region's. An Intake questionnaire's free-text answers are drafted in one call (extract)."""
from __future__ import annotations

from dataclasses import asdict

from pydantic import BaseModel

from app.ctx import Ctx
from app.llm import Lane, complete
from app.record import critic
from app.record.types import Document, DraftFact, FactResource, Finding, Region
from app import trace
from app.trace.events import IntakeDrafted


class _DraftFactOut(BaseModel):
    """Model output schema. Private to this file; parsed into DraftFact before leaving."""
    resource: str
    subject: str
    value: str
    unit: str | None = None
    observed_on: str | None = None     # ISO date or null; the critic flags null
    page: int | None = None            # a letter's page comes from the Region it names, not from the model
    quote: str
    question: str | None = None        # "Q8" on an Intake questionnaire
    span_id: str | None = None         # the Region the quote is from, on a page read into Regions


class _IntakeOut(BaseModel):
    facts: list[_DraftFactOut]


SYSTEM = """You are the Intake agent of a clinical-trial matching service. You read de-identified pages of one
patient Document and list the clinical Facts it states. Answer with JSON only:
{"facts": [{"resource": "...", "subject": "...", "value": "...", "unit": null, "observed_on": "YYYY-MM-DD",
            "page": 1, "span_id": null, "quote": "...", "question": null}]}
- resource is one of: Condition, Observation, MedicationStatement, Procedure, AllergyIntolerance.
  Diagnoses and other illnesses are Condition, treatments are Procedure, medicines are MedicationStatement,
  allergies are AllergyIntolerance, anything else is Observation.
- subject is short and lower case ("breast cancer", "chemotherapy", "tamoxifen", "penicillin").
- quote is copied verbatim from the page the Fact is on; page is that page's number.
- When the page is shown as Regions ("[id] (kind) words"), span_id is the id of the one Region the quote is copied
  from, and the quote lies inside that Region; page may be null. Otherwise span_id is null.
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


REGIONS = """This page was read into Regions. Each Region is one block of the page: its id in square brackets, its
kind in brackets, then its words. Draft Facts only from these Regions; span_id names the one a quote is copied from,
for example "{example}"."""


def _region_line(r: Region) -> str:
    return f"[{r.span_id}] ({r.kind}) {r.text}"


def page_prompt(doc: Document, page: int, feedback: tuple[Finding, ...]) -> str:
    """The Intake prompt for one page of a Document read into Regions: its citable Regions, one per line block."""
    regions = doc.intake_regions(page)
    parts = [REGIONS.format(example=regions[0].span_id if regions else "abc:p1:b0"),
             f"--- Page {page} ---\n" + "\n".join(_region_line(r) for r in regions)]
    if feedback:
        parts.append("Your previous answer for this page had these problems. Fix them and answer with the full list "
                     "for this page again:\n" + "\n".join(f"{n}. {f.message}" for n, f in enumerate(feedback, 1)))
    return "\n\n".join(parts)


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


def _to_draft(f: _DraftFactOut, doc: Document, page: int | None = None) -> DraftFact:
    """`page` is the page being read into Regions: the draft's page is then its named Region's (or, for a Region not
    on the Document, the page read, for the Critic to flag), and its span_id that Region's."""
    if page is not None:
        region = doc.region(f.span_id)
        at, span_id = (region.page if region else page), (f.span_id or None)
    else:
        at, span_id = (f.page or 0), None
    return DraftFact(resource=_resource(f.resource), subject=f.subject.strip().lower(), value=f.value.strip(),
                     unit=f.unit or None, observed_on=critic.observed_on(f.observed_on, doc), page=at,
                     quote=f.quote.strip(), question=(f.question or None) if doc.is_questionnaire else None,
                     span_id=span_id)


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


async def extract_page(ctx: Ctx, doc: Document, page: int, feedback: tuple[Finding, ...], attempt: int,
                       run_id: trace.RunId) -> tuple[DraftFact, ...]:
    """One Intake call for one page of a Document read into Regions. Feedback is about this page's earlier drafts."""
    out = await complete(ctx, Lane.FAST, system=SYSTEM, user=page_prompt(doc, page, feedback), out=_IntakeOut,
                         run_id=run_id)
    drafts = tuple(_to_draft(f, doc, page) for f in out.value.facts)
    await trace.append(ctx.writer, run_id, IntakeDrafted(
        actor="intake", attempt=attempt, drafts=[asdict(d) for d in drafts], model_answered=out.model_answered))
    return drafts
