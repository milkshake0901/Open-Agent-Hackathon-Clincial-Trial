"""app/record — PATIENT RECORD module. Public surface.

Owns: Documents, Facts, Profile versions, Conflicts, and the Intake⇄Critic loop.
Hides: PDF parsing, de-identification, two prompts, conflict rules, retry policy,
Postgres transactions, Zetaris read-after-write waits.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
from dataclasses import asdict, dataclass, replace
from typing import Any

from app import logfile, trace, trials
from app.ctx import Ctx
from app.record import diagnosis as shortlists, loop, questionnaire, repo, storage
from app.record.loop import InvalidResolution, NotAwaitingPatient
from app.record.deidentify import deidentify
from app.record.pdf import UnreadableDocument, to_pages
from app.record.questionnaire import (
    DEFINITION, InvalidAnswers, Option, Question, Questionnaire, Section, SubmittedAnswers,
)
from app.record.types import (
    DIAGNOSIS_ANSWERS,
    AwaitingPatient,
    Committed,
    Conflict,
    ConflictId,
    DiagnosisAnswer,
    DiagnosisCheck,
    DiagnosisCheckId,
    Document,
    DocumentHash,
    DraftFact,
    Fact,
    FactId,
    IngestOutcome,
    Page,
    PatientId,
    ProfileVersion,
    ProfileVersionId,
    Rejected,
    ReturnTokenHash,
    Resolution,
    Respondent,
    SearchPreferences,
    VersionDiff,
    new_diagnosis_check_id,
    new_patient_id,
)
from app.trace import RunId
from app.trace.events import ProfileCommitted

__all__ = [
    "register_document", "register_questionnaire", "ingest", "confirm", "conflicts", "versions", "profile_version", "diff",
    "current_version", "questionnaire_definition", "submit_questionnaire", "create_patient",
    "document", "Registered", "UnreadableDocument", "issue_return_link", "patient_for_return_link",
    "latest_answers", "SubmittedAnswers", "search_preferences", "set_search_preferences", "SearchPreferences",
    "deidentify_text", "check_diagnosis", "answer_diagnosis_check", "diagnosis", "DiagnosisCheck", "DiagnosisAnswer",
    "AlreadyAnswered",
    "NotAwaitingPatient", "InvalidResolution", "Questionnaire", "Section", "Question", "Option", "InvalidAnswers", "Respondent", "NotFound",
    "Document", "DraftFact", "Fact", "ProfileVersion", "Conflict", "Resolution", "VersionDiff",
    "IngestOutcome", "Committed", "AwaitingPatient", "Rejected",
    "PatientId", "ConflictId", "DocumentHash", "ProfileVersionId", "FactId", "DiagnosisCheckId",
]

log = logging.getLogger(__name__)


class NotFound(LookupError):
    """Unknown patient, Document or Profile version id."""


class AlreadyAnswered(InvalidAnswers):
    """The Diagnosis check was answered already: it is not awaiting an answer."""


async def _require_patient(ctx: Ctx, patient_id: PatientId) -> None:
    if not await repo.patient_exists(ctx.ui_reader, patient_id):
        raise NotFound(f"patient {patient_id}")


async def create_patient(ctx: Ctx, label: str) -> PatientId:
    """A new patient with a de-identified display label (never a real name)."""
    patient_id = new_patient_id()
    async with ctx.writer.transaction() as tx:
        await repo.insert_patient(tx, patient_id, label)
    return patient_id


def _token_hash(token: str) -> ReturnTokenHash:
    return ReturnTokenHash(hashlib.sha256(token.encode()).hexdigest())


async def issue_return_link(ctx: Ctx, patient_id: PatientId) -> str | None:
    """The private, unguessable token behind the patient's return link (no accounts or passwords). Issued
    once per patient, on the first submission; None if the patient already has one. Only its hash is
    stored, so it cannot be shown again."""
    await _require_patient(ctx, patient_id)
    token = secrets.token_urlsafe(32)
    async with ctx.writer.transaction() as tx:
        issued = await repo.insert_return_token(tx, _token_hash(token), patient_id)
    return token if issued else None


async def patient_for_return_link(ctx: Ctx, token: str) -> PatientId:
    """The one patient a return token opens. NotFound (saying nothing about any patient) otherwise."""
    patient_id = await repo.patient_for_token_hash(ctx.ui_reader, _token_hash(token))
    if patient_id is None:
        raise NotFound("This return link is not valid.")
    return patient_id


async def document(ctx: Ctx, document_hash: DocumentHash) -> Document:
    """A Document with its de-identified pages; for a questionnaire, also who answered it."""
    doc = await repo.document(ctx.ui_reader, document_hash)
    if doc is None:
        raise NotFound(f"document {document_hash}")
    return doc


async def register_questionnaire(ctx: Ctx, patient_id: PatientId, answers: dict[str, Any],
                                 respondent: Respondent) -> Registered:
    """A completed Intake questionnaire becomes a Document (one page per section, each answer under its question
    number; Respondent stored with the Document; ADR 0003) and its Search preferences are stored. Ingest it with
    ingest(), as an added Document. Raises InvalidAnswers and NotFound before anything is stored. Answers identical
    to the latest accepted submission are that submission's Document (deduplicated)."""
    if respondent not in ("patient", "other"):
        raise InvalidAnswers(f"respondent must be 'patient' or 'other', got {respondent!r}")
    pages = questionnaire.render(answers, respondent)
    preferences = questionnaire.search_preferences(answers)
    await _require_patient(ctx, patient_id)
    previous = await repo.latest_questionnaire(ctx.ui_reader, patient_id)
    h = questionnaire.document_hash(patient_id, pages, respondent, previous)
    existing = await repo.document(ctx.ui_reader, h)
    now = ctx.now()
    doc = existing or Document(hash=h, patient_id=patient_id, filename=questionnaire.DOCUMENT_FILENAME, pages=pages,
                               uploaded_at=now.date(), respondent=respondent)
    async with ctx.writer.transaction() as tx:
        await repo.upsert_search_preferences(tx, patient_id, preferences)
        if existing is None:
            await repo.insert_document(tx, doc, uploaded_at=now)
    return Registered(doc, deduplicated=existing is not None)


async def submit_questionnaire(ctx: Ctx, patient_id: PatientId, answers: dict[str, Any],
                               respondent: Respondent) -> IngestOutcome:
    """register_questionnaire, then ingest to a terminal state. Structured answers map to Patient-reported Facts in
    code, with no model call. Free-text answers (diagnosis, treatments, medicines, allergies, other illnesses) go
    through the Intake agent, which sees only those answers; approximate dates are accepted as best estimates and
    the quote keeps the Respondent's words. Idempotent on identical answers."""
    registered = await register_questionnaire(ctx, patient_id, answers, respondent)
    return await ingest(ctx, registered.document.hash)


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


async def set_search_preferences(ctx: Ctx, patient_id: PatientId, answers: dict[str, Any]) -> SearchPreferences:
    """Set Search preferences on their own, outside a questionnaire submission: `answers` holds only postcode,
    max_travel_km and contact, as the questionnaire takes them and validated the same way; a blank one keeps its
    stored value. Never a Fact, so no new Profile version. Raises InvalidAnswers (before anything is stored) and
    NotFound."""
    others = sorted(set(answers) - set(questionnaire.SEARCH_PREFERENCES))
    if others:
        raise InvalidAnswers(f"not search preferences: {others}")
    changes = questionnaire.search_preferences(answers)
    await _require_patient(ctx, patient_id)
    async with ctx.writer.transaction() as tx:
        await repo.upsert_search_preferences(tx, patient_id, changes)
    return await repo.search_preferences(ctx.ui_reader, patient_id)


async def check_diagnosis(ctx: Ctx, patient_id: PatientId, text: str | None = None) -> DiagnosisCheck:
    """A shortlist of Condition labels stored Trials use, for the diagnosis in the Respondent's words: `text` (a
    re-wording), else the latest accepted questionnaire's diagnosis answer (ADR 0005). The words are de-identified
    (deidentify_text) before the model sees them, the check stores them or the log file records them; the model sees
    only those words and the candidate labels. The check comes back `proposed` for the Respondent to answer; its
    shortlist is empty when no label fits (they can only re-word or answer not sure). What to say for each status is
    the HTTP shell's. Raises NotFound (unknown patient, or no diagnosis to check) and llm.LlmUnavailable (nothing
    stored)."""
    await _require_patient(ctx, patient_id)
    if text is None:
        answered = await latest_answers(ctx, patient_id)
        text = (answered.answers.get("diagnosis") if answered else None) or None
    check = await _new_check(ctx, patient_id, text)
    if check is None:
        raise NotFound(f"no diagnosis answer for patient {patient_id}")
    async with ctx.writer.transaction() as tx:
        await repo.insert_diagnosis_check(tx, check, ctx.now())
    _log_offered(check)
    return check


async def _new_check(ctx: Ctx, patient_id: PatientId, text: str | None) -> DiagnosisCheck | None:
    """A proposed check for the de-identified words, not stored yet; None when there are no words."""
    words = _diagnosis_words(text)
    if not words:
        return None
    return DiagnosisCheck(id=new_diagnosis_check_id(), patient_id=patient_id, text=words,
                          shortlist=await shortlists.shortlist(ctx, words), status="proposed")


def _diagnosis_words(text: str | None) -> str:
    return " ".join(deidentify_text(text).split()) if text and text.strip() else ""


async def answer_diagnosis_check(ctx: Ctx, patient_id: PatientId, check_id: DiagnosisCheckId,
                                 answer: DiagnosisAnswer, *, labels: tuple[str, ...] = (),
                                 text: str | None = None) -> DiagnosisCheck:
    """The Respondent's answer to a proposed check. "ticked" with one or more of its shortlist `labels` (equal
    ignoring case and spacing) makes them the patient's Condition term, which selects the Trials judged and shown;
    "none_of_these" asks again, and with new words `text` starts a new check (check_diagnosis), which is returned
    instead; "not_sure" tells them to check with their GP and raises a Doctor question for the diagnosis. Answered
    once; with new words, the answer and the new check are stored together or not at all. Raises NotFound (not this
    patient's check), InvalidAnswers (an unknown answer, labels missing or not in the shortlist; AlreadyAnswered, a
    subclass, when the check is not awaiting an answer) and, for new words, llm.LlmUnavailable (nothing stored)."""
    if answer not in DIAGNOSIS_ANSWERS:
        raise InvalidAnswers(f"answer must be ticked, none_of_these or not_sure, got {answer!r}")
    check = await repo.diagnosis_check(ctx.ui_reader, check_id)
    if check is None or check.patient_id != patient_id:
        raise NotFound(f"diagnosis check {check_id}")
    if check.status != "proposed":
        raise AlreadyAnswered(f"diagnosis check {check_id} is {check.status}, not awaiting an answer")
    ticked: tuple[str, ...] = ()
    if answer == "ticked":
        wanted = {trials.label_key(label) for label in labels}
        ticked = tuple(one.label for one in check.shortlist if trials.label_key(one.label) in wanted)
        if not wanted or len(ticked) != len(wanted):
            raise InvalidAnswers(f"tick one or more labels from diagnosis check {check_id}'s shortlist")
    answered = replace(check, status=answer, ticked=ticked)
    again = await _new_check(ctx, patient_id, text) if answer == "none_of_these" else None   # before any write
    async with ctx.writer.transaction() as tx:
        stored = await repo.answer_diagnosis_check(tx, answered, ctx.now())
        if not stored:
            raise AlreadyAnswered(f"diagnosis check {check_id} is not awaiting an answer")
        if again is not None:
            await repo.insert_diagnosis_check(tx, again, ctx.now())
    logfile.step(log, "record.diagnosis_check.answered", patient_id=patient_id,   # #35
                 answer={"answer": answer, "labels": list(labels), "text": _diagnosis_words(text) or None},
                 check=_check_line(answered))
    if again is not None:
        _log_offered(again)
        return again
    return answered


def _log_offered(check: DiagnosisCheck) -> None:
    logfile.step(log, "record.diagnosis_check.offered", patient_id=check.patient_id, check=_check_line(check))  # #35


def _check_line(check: DiagnosisCheck) -> dict[str, Any]:
    """A check as the log file shows it: its de-identified words, shortlist and answer."""
    return {"id": check.id, "text": check.text, "shortlist": [asdict(one) for one in check.shortlist],
            "ticked": list(check.ticked), "status": check.status, "condition": check.condition_term}


async def diagnosis(ctx: Ctx, patient_id: PatientId) -> DiagnosisCheck | None:
    """The check that holds for the patient: the latest one settled as ticked (its `condition_term` selects the Trials
    judged and shown) or not sure (`needs_gp`). None while nothing is settled."""
    return await repo.settled_diagnosis_check(ctx.ui_reader, patient_id)


def deidentify_text(text: str) -> str:
    """One piece of text with names, addresses, record numbers and contact details replaced by placeholders, by the
    same rules a Document's pages go through (De-identification); for text built outside a Document, such as an
    Enquiry's clinical details, before a model sees it."""
    return deidentify((Page(number=1, text=text),))[0].text


def questionnaire_definition() -> Questionnaire:
    """The Intake questionnaire as data: sections, questions (numbered), answer kinds, options and the
    "your"/"their" wording. Every question can be skipped."""
    return DEFINITION


@dataclass(frozen=True)
class Registered:
    document: Document
    deduplicated: bool    # this Document was already stored for this patient; nothing was parsed or stored


async def register_document(ctx: Ctx, patient_id: PatientId, filename: str, content: bytes) -> Registered:
    """Hash content, parse pages, de-identify, persist document+pages. Idempotent on hash (per patient):
    adding the same bytes twice returns the existing Document and does not re-parse.
    De-identified page text is what Citations display; raw bytes are kept only on disk (settings.raw_documents_dir).
    Raises UnreadableDocument (not a PDF, or no text layer) and NotFound before anything is stored."""
    await _require_patient(ctx, patient_id)
    h = storage.document_hash(patient_id, content)
    existing = await repo.document(ctx.ui_reader, h)
    if existing is not None:
        return Registered(existing, deduplicated=True)
    pages = deidentify(to_pages(content))
    now = ctx.now()
    doc = Document(hash=h, patient_id=patient_id, filename=storage.filename(filename), pages=pages,
                   uploaded_at=now.date())
    storage.keep_raw(ctx.settings.raw_documents_dir, h, content)
    async with ctx.writer.transaction() as tx:
        await repo.insert_document(tx, doc, uploaded_at=now)
    return Registered(doc, deduplicated=False)


async def ingest(ctx: Ctx, document_hash: DocumentHash, *, run_id: RunId | None = None) -> IngestOutcome:
    """Run the Intake⇄Critic loop for one Document to its terminal state.

    Terminal states (exhaustive, see record.loop):
      Committed        a new ProfileVersion exists; Facts inserted in one transaction.
      AwaitingPatient  the run is parked with Conflicts the patient must resolve (record.confirm).
      Rejected         nothing acceptable after bounded attempts, or document unreadable.

    Idempotent: if a ProfileVersion for this document_hash already exists, returns
    Committed for it without calling any model. If a run for this document is already
    AwaitingPatient, returns that AwaitingPatient (rehydrated from the run log, no model call).

    `run_id` lets the caller open the run first (adding a Document or submitting a questionnaire answers 202 with it); it
    is opened here otherwise. Ingests for one patient run one at a time. An Intake questionnaire's structured
    answers are drafted in code and only its free-text answers reach the Intake agent (record.loop.drafter_for).
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
    async with loop.patient_lock(doc.patient_id):
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
    async with loop.patient_lock(doc.patient_id):
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
