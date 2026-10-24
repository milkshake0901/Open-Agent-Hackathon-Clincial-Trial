"""app/record — PATIENT RECORD module. Public surface.

Owns: Documents, Facts, Profile versions, Conflicts, and the Intake⇄Critic loop.
Hides: PDF parsing, de-identification, two prompts, conflict rules, retry policy,
Postgres transactions, Zetaris read-after-write waits.
"""
from __future__ import annotations

import asyncio
import hashlib
import secrets
import uuid
from dataclasses import dataclass, replace
from pathlib import Path, PurePath
from typing import Any

from app import trace
from app.ctx import Ctx
from app.record import diagnosis as diagnosis_terms, loop, questionnaire, repo
from app.record.loop import InvalidResolution, NotAwaitingPatient
from app.record.deidentify import deidentify
from app.record.pdf import UnreadableDocument, to_pages
from app.record.questionnaire import (
    DEFINITION, InvalidAnswers, Option, Question, Questionnaire, Section, SubmittedAnswers,
)
from app.record.types import (
    AwaitingPatient,
    Committed,
    Conflict,
    ConflictId,
    DiagnosisAnswer,
    DiagnosisCheck,
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
    SearchPreferences,
    VersionDiff,
)
from app.trace import RunId
from app.trace.events import ProfileCommitted

__all__ = [
    "register_document", "ingest", "confirm", "conflicts", "versions", "profile_version", "diff",
    "current_version", "questionnaire_definition", "submit_questionnaire", "create_patient",
    "document", "Registered", "UnreadableDocument", "issue_return_token", "patient_for_return_token",
    "latest_answers", "SubmittedAnswers", "search_preferences", "SearchPreferences",
    "check_diagnosis", "answer_diagnosis_check", "diagnosis", "DiagnosisCheck", "DiagnosisAnswer",
    "NotAwaitingPatient", "InvalidResolution", "Questionnaire", "Section", "Question", "Option", "InvalidAnswers", "Respondent", "NotFound",
    "Document", "DraftFact", "Fact", "ProfileVersion", "Conflict", "Resolution", "VersionDiff",
    "IngestOutcome", "Committed", "AwaitingPatient", "Rejected",
    "PatientId", "ConflictId", "DocumentHash", "ProfileVersionId", "FactId",
]


class NotFound(LookupError):
    """Unknown patient, Document or Profile version id."""


async def create_patient(ctx: Ctx, label: str) -> PatientId:
    """A new patient with a de-identified display label (never a real name)."""
    patient_id = PatientId(f"pt_{uuid.uuid4().hex[:16]}")
    async with ctx.writer.transaction() as tx:
        await repo.insert_patient(tx, patient_id, label)
    return patient_id


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def issue_return_token(ctx: Ctx, patient_id: PatientId) -> str | None:
    """The private, unguessable token behind the patient's return link (no accounts or passwords). Issued
    once per patient, on the first submission; None if the patient already has one. Only its hash is
    stored, so it cannot be shown again."""
    if not await repo.patient_exists(ctx.ui_reader, patient_id):
        raise NotFound(f"patient {patient_id}")
    token = secrets.token_urlsafe(32)
    async with ctx.writer.transaction() as tx:
        issued = await repo.insert_return_token(tx, _token_hash(token), patient_id)
    return token if issued else None


async def patient_for_return_token(ctx: Ctx, token: str) -> PatientId:
    """The one patient a return token opens. NotFound (saying nothing about any patient) otherwise."""
    patient_id = await repo.patient_for_token_hash(ctx.ui_reader, _token_hash(token))
    if patient_id is None:
        raise NotFound("return link")
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
    preferences = questionnaire.preferences(answers)
    if not await repo.patient_exists(ctx.ui_reader, patient_id):
        raise NotFound(f"patient {patient_id}")
    now = ctx.now()
    drafts = questionnaire.structured_drafts(answers, respondent, pages, now.date())
    # Document hashes are global keys, so the patient is part of a questionnaire's identity: two patients
    # giving the same answers submit two Documents. A correction is a new Document (ADR 0003) even when it
    # changes an answer back, so the hash also names the previous accepted questionnaire; answers identical
    # to that one are the same submission and return its version.
    body = "\f".join(p.text for p in pages)
    previous = await repo.latest_questionnaire(ctx.ui_reader, patient_id)
    if previous is not None and previous.respondent == respondent and "\f".join(p.text for p in previous.pages) == body:
        h = previous.hash
    else:
        after = f"after {previous.hash}\n" if previous is not None else ""
        h = DocumentHash(hashlib.sha256(f"intake-questionnaire\n{patient_id}\n{after}{body}".encode()).hexdigest())
    doc = Document(hash=h, patient_id=patient_id, filename=questionnaire.DOCUMENT_FILENAME, pages=pages,
                   uploaded_at=now.date(), respondent=respondent)
    async with ctx.writer.transaction() as tx:
        await repo.upsert_search_preferences(tx, patient_id, preferences)
        await repo.insert_document(tx, doc, uploaded_at=now)
    existing = await repo.version_for_document(ctx.ui_reader, h)
    if existing is not None:
        return Committed(await trace.latest_for_document(ctx.ui_reader, h) or trace.new_id(), existing)
    run_id = trace.new_id()
    await trace.open(ctx.writer, run_id, "ingest", patient_id=patient_id, document_hash=h)
    free_text = replace(doc, pages=questionnaire.free_text_pages(answers, respondent))
    return await loop.run_ingest(ctx, doc, run_id, ctx.settings.intake_attempts,
                                 drafter=loop.questionnaire_drafter(drafts, free_text, questionnaire.settle_free_text))


async def latest_answers(ctx: Ctx, patient_id: PatientId) -> SubmittedAnswers | None:
    """The latest accepted Intake questionnaire's answers and Respondent, read back from its Document, so an
    edit starts prefilled. None before the first accepted submission. Search preferences (postcode, travel, contact)
    are never in a Document, so never here: a resubmission that leaves them blank keeps the stored values."""
    doc = await repo.latest_questionnaire(ctx.ui_reader, patient_id)
    if doc is None:
        return None
    return SubmittedAnswers(document_hash=doc.hash, respondent=doc.respondent,
                            answers=questionnaire.answers_from_pages(doc.pages))


async def search_preferences(ctx: Ctx, patient_id: PatientId) -> SearchPreferences:
    """Postcode, travel limit and optional contact from the latest submissions that answered them (a skipped
    preference keeps its stored value). Never a Fact; never pass any of it to a model (ADR 0003)."""
    return await repo.search_preferences(ctx.ui_reader, patient_id)


async def check_diagnosis(ctx: Ctx, patient_id: PatientId, text: str | None = None) -> DiagnosisCheck:
    """A model proposes a condition term for the diagnosis in the Respondent's words: `text` (a re-wording after
    "no"), else the latest accepted questionnaire's diagnosis answer. The model sees only those words. A confident
    term comes back `proposed`, for the Respondent to answer ("We understood this as ..., is that right?");
    otherwise nothing is offered and the check is `unclear`, which settles the diagnosis as needing the GP.
    Raises NotFound (unknown patient, or no diagnosis to check) and llm.LlmUnavailable (nothing stored)."""
    if not await repo.patient_exists(ctx.ui_reader, patient_id):
        raise NotFound(f"patient {patient_id}")
    if text is None:
        answered = await latest_answers(ctx, patient_id)
        text = (answered.answers.get("diagnosis") if answered else None) or None
    text = " ".join((text or "").split())
    if not text:
        raise NotFound(f"no diagnosis answer for patient {patient_id}")
    term, confidence = await diagnosis_terms.propose_term(ctx, text)
    check = DiagnosisCheck(id=f"dx_{uuid.uuid4().hex[:16]}", patient_id=patient_id, text=text, suggested_term=term,
                           confidence=confidence, status="proposed" if term else "unclear")
    async with ctx.writer.transaction() as tx:
        await repo.insert_diagnosis_check(tx, check, ctx.now())
    return check


_ANSWER_STATUS = {"yes": "confirmed", "no": "rejected", "not_sure": "not_sure"}


async def answer_diagnosis_check(ctx: Ctx, patient_id: PatientId, check_id: str,
                                 answer: DiagnosisAnswer) -> DiagnosisCheck:
    """The Respondent's yes / no / not sure to a proposed term. "yes" makes it the patient's condition (it selects
    which Trials are judged); "no" asks again (check_diagnosis with their re-wording); "not sure" tells them to
    check with their GP and raises a Doctor question for the diagnosis. Answered once. Raises NotFound (not this
    patient's check) and InvalidAnswers (an unknown answer, or the check is not awaiting one)."""
    if answer not in _ANSWER_STATUS:
        raise InvalidAnswers(f"answer must be yes, no or not_sure, got {answer!r}")
    check = await repo.diagnosis_check(ctx.ui_reader, check_id)
    if check is None or check.patient_id != patient_id:
        raise NotFound(f"diagnosis check {check_id}")
    async with ctx.writer.transaction() as tx:
        answered = await repo.answer_diagnosis_check(tx, check_id, _ANSWER_STATUS[answer], ctx.now())
    if not answered:
        raise InvalidAnswers(f"diagnosis check {check_id} is {check.status}, not awaiting an answer")
    return replace(check, status=_ANSWER_STATUS[answer])


async def diagnosis(ctx: Ctx, patient_id: PatientId) -> DiagnosisCheck | None:
    """The check that holds for the patient: the latest one settled as confirmed (its `condition` drives Trial
    selection), not sure or unclear (`needs_gp`). None while nothing is settled, so every active Trial is judged."""
    return await repo.settled_diagnosis_check(ctx.ui_reader, patient_id)


def questionnaire_definition() -> Questionnaire:
    """The Intake questionnaire as data: sections, questions (numbered), answer kinds, options and the
    "your"/"their" wording. Every question can be skipped."""
    return DEFINITION


@dataclass(frozen=True)
class Registered:
    document: Document
    deduplicated: bool    # these bytes were already uploaded for this patient; nothing was parsed or stored


def document_hash(patient_id: PatientId, content: bytes) -> DocumentHash:
    """Document hashes are global keys, so the patient is part of an upload's identity: the same bytes from two
    patients are two Documents, and one patient's upload can never resolve to another patient's pages."""
    return DocumentHash(hashlib.sha256(f"document\n{patient_id}\n".encode() + content).hexdigest())


async def register_document(ctx: Ctx, patient_id: PatientId, filename: str, content: bytes) -> Registered:
    """Hash content, parse pages, de-identify, persist document+pages. Idempotent on hash (per patient):
    uploading the same bytes twice returns the existing Document and does not re-parse.
    De-identified page text is what Citations display; raw bytes are kept only on disk (settings.raw_documents_dir).
    Raises UnreadableDocument (not a PDF, or no text layer) and NotFound before anything is stored."""
    if not await repo.patient_exists(ctx.ui_reader, patient_id):
        raise NotFound(f"patient {patient_id}")
    h = document_hash(patient_id, content)
    existing = await repo.document(ctx.ui_reader, h)
    if existing is not None:
        return Registered(existing, deduplicated=True)
    pages = deidentify(to_pages(content))
    now = ctx.now()
    doc = Document(hash=h, patient_id=patient_id, filename=PurePath(filename.replace("\\", "/")).name or "document.pdf",
                   pages=pages, uploaded_at=now.date())
    raw = Path(ctx.settings.raw_documents_dir)
    raw.mkdir(parents=True, exist_ok=True)
    (raw / f"{h}.pdf").write_bytes(content)
    async with ctx.writer.transaction() as tx:
        await repo.insert_document(tx, doc, uploaded_at=now)
    return Registered(doc, deduplicated=False)


_patient_locks: dict[PatientId, asyncio.Lock] = {}


def _patient_lock(patient_id: PatientId) -> asyncio.Lock:
    """One ingest at a time per patient (in this process): each commit numbers its version from the previous
    one, so several uploads in one go become v2, v3, ... in turn instead of racing for the same number."""
    return _patient_locks.setdefault(patient_id, asyncio.Lock())


async def ingest(ctx: Ctx, document_hash: DocumentHash, *, run_id: RunId | None = None) -> IngestOutcome:
    """Run the Intake⇄Critic loop for one Document to its terminal state.

    Terminal states (exhaustive, see record.loop):
      Committed        a new ProfileVersion exists; Facts inserted in one transaction.
      AwaitingPatient  the run is parked with Conflicts the patient must resolve (record.confirm).
      Rejected         nothing acceptable after bounded attempts, or document unreadable.

    Idempotent: if a ProfileVersion for this document_hash already exists, returns
    Committed for it without calling any model. If a run for this document is already
    AwaitingPatient, returns that AwaitingPatient (rehydrated from the run log, no model call).

    `run_id` lets the caller open the run first (an upload answers 202 with it); it is opened here otherwise.
    Ingests for one patient run one at a time.
    """
    doc = await repo.document(ctx.ui_reader, document_hash)
    if doc is None:
        raise NotFound(f"document {document_hash}")
    if run_id is None:
        existing = await repo.version_for_document(ctx.ui_reader, doc.hash)
        if existing is not None:
            return Committed(await trace.latest_for_document(ctx.ui_reader, doc.hash) or trace.new_id(), existing)
        earlier = await trace.latest_for_document(ctx.ui_reader, doc.hash)
        if earlier is not None and (waiting := loop.parked(await trace.project_ingest(ctx.ui_reader, earlier), earlier)):
            return waiting
        run_id = trace.new_id()
    await trace.open(ctx.writer, run_id, "ingest", patient_id=doc.patient_id, document_hash=doc.hash)
    async with _patient_lock(doc.patient_id):
        existing = await repo.version_for_document(ctx.ui_reader, doc.hash)
        if existing is not None:   # the caller's run ends where an earlier run for these bytes already did
            await trace.append(ctx.writer, run_id, ProfileCommitted(
                actor="record", profile_version_id=existing.id, version_number=existing.number, facts_added=0))
            return Committed(run_id, existing)
        return await loop.run_ingest(ctx, doc, run_id, ctx.settings.intake_attempts)


async def confirm(ctx: Ctx, run_id: RunId, resolutions: list[Resolution]) -> IngestOutcome:
    """Patient resolves Conflicts on a parked run. Keeps the loop's accepted draft facts,
    applies the chosen values, commits. Partial resolutions leave the run AwaitingPatient
    with the remaining Conflicts. Rejected drafts are never inserted (Facts stay append-only).

    Choices: keep_accepted (the draft is dropped), accept_draft (the draft is committed and the accepted Fact it
    contradicts is left out of the new version), discard_both (neither is in the new version). Earlier versions
    are unchanged. Raises NotFound (unknown run), NotAwaitingPatient, InvalidResolution."""
    try:
        state = await trace.project_ingest(ctx.ui_reader, run_id)
    except trace.UnknownRun:
        raise NotFound(f"run {run_id}")
    if state.phase != "awaiting_patient":
        raise NotAwaitingPatient(f"run {run_id} is {state.phase}, not awaiting the patient")
    log = await trace.read(ctx.ui_reader, run_id)
    started = next(e.event for e in log.events if e.event.kind == "ingest.started")
    doc = await repo.document(ctx.ui_reader, DocumentHash(started.document_hash))
    async with _patient_lock(doc.patient_id):
        return await loop.resume_after_confirm(ctx, doc, run_id, resolutions)


async def conflicts(ctx: Ctx, run_id: RunId) -> tuple[Conflict, ...]:
    """The Conflicts a parked ingest run is still waiting on (empty once it has moved on). Raises NotFound."""
    try:
        state = await trace.project_ingest(ctx.ui_reader, run_id)
    except trace.UnknownRun:
        raise NotFound(f"run {run_id}")
    waiting = loop.parked(state, run_id)
    return waiting.conflicts if waiting else ()


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
    """Facts added between two versions and subjects whose current value changed. Pure over two loads.
    A subject is changed when its current value (or unit) differs, or it is new; a later Fact repeating the
    same value is added but not a change."""
    before, after = await profile_version(ctx, from_version), await profile_version(ctx, to_version)
    if before.patient_id != after.patient_id:
        raise NotFound(f"profile versions {from_version} and {to_version} belong to different patients")
    was, now = before.current(), after.current()
    changed = tuple((s, was.get(s), f) for s, f in now.items()
                    if s not in was or (was[s].value, was[s].unit) != (f.value, f.unit))
    return VersionDiff(from_version=before.id, to_version=after.id,
                       facts_added=tuple(f for f in after.facts if f.id not in before.fact_ids),
                       subjects_changed=changed)
