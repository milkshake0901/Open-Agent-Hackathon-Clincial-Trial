"""app/record — PATIENT RECORD module. Public surface.

Owns: Documents, Facts, Profile versions, Conflicts, and the Intake⇄Critic loop.
Hides: PDF parsing, de-identification, two prompts, conflict rules, retry policy,
Postgres transactions, Zetaris read-after-write waits.
"""
from __future__ import annotations

import hashlib
import uuid
from dataclasses import replace
from typing import Any

from app import trace
from app.ctx import Ctx
from app.record import loop, questionnaire, repo
from app.record.questionnaire import DEFINITION, InvalidAnswers, Option, Question, Questionnaire, Section
from app.record.types import (
    AwaitingPatient,
    Committed,
    Conflict,
    Document,
    DocumentHash,
    DraftFact,
    Fact,
    FactId,
    IngestOutcome,
    PatientId,
    ProfileVersion,
    ProfileVersionId,
    Rejected,
    Resolution,
    Respondent,
    VersionDiff,
)
from app.trace import RunId

__all__ = [
    "register_document", "ingest", "confirm", "versions", "profile_version", "diff",
    "current_version", "questionnaire_definition", "submit_questionnaire", "create_patient",
    "document", "Questionnaire", "Section", "Question", "Option", "InvalidAnswers", "Respondent", "NotFound",
    "Document", "DraftFact", "Fact", "ProfileVersion", "Conflict", "Resolution", "VersionDiff",
    "IngestOutcome", "Committed", "AwaitingPatient", "Rejected",
    "PatientId", "DocumentHash", "ProfileVersionId", "FactId",
]


class NotFound(LookupError):
    """Unknown patient, Document or Profile version id."""


async def create_patient(ctx: Ctx, label: str) -> PatientId:
    """A new patient with a de-identified display label (never a real name)."""
    patient_id = PatientId(f"pt_{uuid.uuid4().hex[:16]}")
    async with ctx.writer.transaction() as tx:
        await repo.insert_patient(tx, patient_id, label)
    return patient_id


async def document(ctx: Ctx, document_hash: DocumentHash) -> Document:
    """A Document with its de-identified pages; for a questionnaire, also who answered it."""
    doc = await repo.document(ctx.ui_reader, document_hash)
    if doc is None:
        raise NotFound(f"document {document_hash}")
    return doc


async def submit_questionnaire(ctx: Ctx, patient_id: PatientId, answers: dict[str, Any],
                               respondent: Respondent) -> IngestOutcome:
    """A completed Intake questionnaire becomes a Document (one page per section, each answer under its
    question number; Respondent stored with the Document) and goes through the ingest loop (ADR 0003).
    Structured answers map to Patient-reported Facts in code, with no model call. Free-text answers (diagnosis,
    treatments, medicines, allergies, other illnesses) go through the Intake agent, which sees only those
    answers; approximate dates are accepted as best estimates and the quote keeps the Respondent's words.
    Raises InvalidAnswers before anything is stored if an answer does not fit its question. Idempotent on
    identical answers."""
    if respondent not in ("patient", "other"):
        raise InvalidAnswers(f"respondent must be 'patient' or 'other', got {respondent!r}")
    pages = questionnaire.render(answers, respondent)
    if not await repo.patient_exists(ctx.ui_reader, patient_id):
        raise NotFound(f"patient {patient_id}")
    now = ctx.now()
    drafts = questionnaire.structured_drafts(answers, respondent, pages, now.date())
    # Document hashes are global keys, so the patient is part of a questionnaire's identity: two patients
    # giving the same answers submit two Documents.
    body = "\f".join(p.text for p in pages)
    h = DocumentHash(hashlib.sha256(f"intake-questionnaire\n{patient_id}\n{body}".encode()).hexdigest())
    doc = Document(hash=h, patient_id=patient_id, filename=questionnaire.DOCUMENT_FILENAME, pages=pages,
                   uploaded_at=now.date(), respondent=respondent)
    async with ctx.writer.transaction() as tx:
        await repo.insert_document(tx, doc, uploaded_at=now)
    existing = await repo.version_for_document(ctx.ui_reader, h)
    if existing is not None:
        return Committed(await trace.latest_for_document(ctx.ui_reader, h) or trace.new_id(), existing)
    run_id = trace.new_id()
    await trace.open(ctx.writer, run_id, "ingest", patient_id=patient_id, document_hash=h)
    free_text = replace(doc, pages=questionnaire.free_text_pages(answers, respondent))
    return await loop.run_ingest(ctx, doc, run_id, ctx.settings.intake_attempts,
                                 drafter=loop.questionnaire_drafter(drafts, free_text, questionnaire.settle_free_text))


def questionnaire_definition() -> Questionnaire:
    """The Intake questionnaire as data: sections, questions (numbered), answer kinds, options and the
    "your"/"their" wording. Every question can be skipped."""
    return DEFINITION


async def register_document(ctx: Ctx, patient_id: PatientId, filename: str, content: bytes) -> Document:
    """Hash content, parse pages, de-identify, persist document+pages. Idempotent on hash:
    uploading the same bytes twice returns the existing Document and does not re-parse.
    De-identified page text is what Citations display; raw bytes are kept only on disk (data/raw)."""
    raise NotImplementedError


async def ingest(ctx: Ctx, document_hash: DocumentHash, *, run_id: RunId | None = None) -> IngestOutcome:
    """Run the Intake⇄Critic loop for one Document to its terminal state.

    Terminal states (exhaustive, see record.loop):
      Committed        a new ProfileVersion exists; Facts inserted in one transaction.
      AwaitingPatient  the run is parked with Conflicts the patient must resolve (record.confirm).
      Rejected         nothing acceptable after bounded attempts, or document unreadable.

    Idempotent: if a ProfileVersion for this document_hash already exists, returns
    Committed for it without calling any model. If a run for this document is already
    AwaitingPatient, returns that AwaitingPatient.
    """
    raise NotImplementedError


async def confirm(ctx: Ctx, run_id: RunId, resolutions: list[Resolution]) -> IngestOutcome:
    """Patient resolves Conflicts on a parked run. Keeps the loop's accepted draft facts,
    applies the chosen values, commits. Partial resolutions leave the run AwaitingPatient
    with the remaining Conflicts. Rejected drafts are never inserted (Facts stay append-only)."""
    raise NotImplementedError


async def versions(ctx: Ctx, patient_id: PatientId) -> list[ProfileVersion]:
    raise NotImplementedError


async def current_version(ctx: Ctx, patient_id: PatientId) -> ProfileVersion | None:
    return await repo.current_version(ctx.ui_reader, patient_id)


async def profile_version(ctx: Ctx, version_id: ProfileVersionId, *, for_agent: bool = False) -> ProfileVersion:
    """Load a version with its Facts. for_agent=True reads via ctx.agent_reader (Zetaris, ADR 0001)
    and waits (bounded) until the version is visible there; the HTTP shell uses the default.
    (#7 reads directly; the bounded Zetaris wait arrives with ZetarisReader.)"""
    version = await repo.version(ctx.agent_reader if for_agent else ctx.ui_reader, version_id, with_facts=True)
    if version is None:
        raise NotFound(f"profile version {version_id}")
    return version


async def diff(ctx: Ctx, from_version: ProfileVersionId, to_version: ProfileVersionId) -> VersionDiff:
    """Facts added between two versions and subjects whose current value changed. Pure over two loads."""
    raise NotImplementedError
