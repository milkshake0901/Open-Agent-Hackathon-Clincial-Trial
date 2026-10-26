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
from datetime import date
from typing import Any, Literal

from app import logfile, trace
from app.ctx import Ctx
from app.record import dates, diagnosis as shortlists, loop, questionnaire, repo, storage
from app.record.loop import InvalidResolution, NotAwaitingPatient
from app.record.deidentify import deidentify
from app.record.ground import LetterSpan, letter_spans, page_png
from app.record.pdf import UnreadableDocument
from app.record.questionnaire import (
    DEFINITION, Option, Question, Questionnaire, Section, SubmittedAnswers, cited_answer,
)
from app.record.types import (
    AwaitingPatient,
    AwaitingReview,
    CitedAnswer,
    Committed,
    Conflict,
    ConflictId,
    DiagnosisAnswer,
    DiagnosisCheck,
    DiagnosisCheckId,
    DiagnosisState,
    DiagnosisStep,
    Document,
    DocumentHash,
    DraftFact,
    Fact,
    FactResource,
    INTAKE_KINDS,
    FactId,
    IngestOutcome,
    InvalidAnswers,
    NoneOfThese,
    NotSure,
    Page,
    PatientId,
    ProfileVersion,
    ProfileVersionId,
    Region,
    Rejected,
    ReturnTokenHash,
    Resolution,
    Respondent,
    SearchPreferences,
    Ticked,
    VersionDiff,
    new_diagnosis_check_id,
    new_patient_id,
)
from app.trace import RunId
from app.trace.events import ProfileCommitted, ReviewAnswered

__all__ = [
    "register_document", "register_questionnaire", "ingest", "confirm", "conflicts", "versions", "profile_version", "diff",
    "current_version", "questionnaire_definition", "submit_questionnaire", "create_patient",
    "document", "document_regions", "DocumentRegions", "Region", "Registered", "UnreadableDocument", "issue_return_link", "patient_for_return_link",
    "latest_answers", "SubmittedAnswers", "cited_answer", "CitedAnswer", "search_preferences", "set_search_preferences", "SearchPreferences",
    "deidentify_text", "check_diagnosis", "answer_diagnosis_check", "diagnosis", "diagnosis_step", "DiagnosisCheck",
    "DiagnosisStep", "DiagnosisState", "DiagnosisAnswer",
    "Ticked", "NoneOfThese", "NotSure", "AlreadyAnswered",
    "NotAwaitingPatient", "InvalidResolution", "Questionnaire", "Section", "Question", "Option", "InvalidAnswers", "Respondent", "NotFound",
    "Document", "DraftFact", "Fact", "ProfileVersion", "Conflict", "Resolution", "VersionDiff",
    "IngestOutcome", "Committed", "AwaitingPatient", "AwaitingReview", "Rejected",
    "letter_review", "answer_review", "correct_document_date", "commit_review", "LetterReview", "ReviewItem",
    "ReviewCommitted", "NotAwaitingReview", "InvalidReview",
    "page_png", "letter_spans", "LetterSpan", "INTAKE_KINDS",
    "intake_status", "IntakeStatus", "LetterStatus", "NotReady",
    "PatientId", "ConflictId", "DocumentHash", "ProfileVersionId", "FactId", "DiagnosisCheckId",
]

log = logging.getLogger(__name__)


class NotFound(LookupError):
    """Unknown patient, Document or Profile version id."""


class AlreadyAnswered(InvalidAnswers):
    """The Diagnosis check was answered already: it is not awaiting an answer."""


class NotReady(Exception):
    """A Document of the patient's (a letter, or a questionnaire submission) is still being read, or waits for Letter
    review or the Respondent's answer to a Conflict: the Diagnosis check waits until its Facts are committed."""


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
    to the latest accepted submission are that submission's Document (deduplicated). A question the short form did not
    show (one the letters answer, intake_status skip, or a review-only one) keeps its earlier answer when left blank,
    so a save never withdraws it."""
    if respondent not in ("patient", "other"):
        raise InvalidAnswers(f"respondent must be 'patient' or 'other', got {respondent!r}")
    questionnaire.render(answers, respondent)   # InvalidAnswers before anything is read
    preferences = questionnaire.search_preferences(answers)
    await _require_patient(ctx, patient_id)
    previous = await repo.latest_questionnaire(ctx.ui_reader, patient_id)
    if previous is not None:
        hidden = (await intake_status(ctx, patient_id)).skip
        answers = questionnaire.kept_from(questionnaire.answers_from_pages(previous.pages), answers, hidden)
    pages = questionnaire.render(answers, respondent)
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


@dataclass(frozen=True)
class LetterStatus:
    """One of the patient's letters (a Document read into Regions) and where its latest ingest run stands."""
    document_hash: DocumentHash
    filename: str
    run_id: RunId
    phase: str     # the run's phase: started, drafting, awaiting_patient, awaiting_review, committed, rejected


@dataclass(frozen=True)
class IntakeStatus:
    """Where the patient's letters and questionnaire stand. `skip`: the question ids the letters' Facts answer
    (committed, or drafted and waiting for Letter review without being marked Not right), which the short
    questionnaire skips. `ready`: no Document of the patient's is still being read or waiting on the Respondent, so
    every Fact is committed and the Diagnosis check and Trials can go ahead. `current`: the latest Profile version
    (without its Facts), the one Trials are listed for; None before the first."""
    letters: tuple[LetterStatus, ...]
    skip: frozenset[str]
    ready: bool
    current: ProfileVersion | None = None


_UNSETTLED = ("started", "drafting", "awaiting_patient", "awaiting_review")


async def intake_status(ctx: Ctx, patient_id: PatientId) -> IntakeStatus:
    """The patient's letters with their runs, the questions they answer, and whether every Document is committed (or
    rejected). Raises NotFound."""
    await _require_patient(ctx, patient_id)
    letters, resources, ready = [], set(), True
    for run_id, h in await trace.latest_ingests(ctx.ui_reader, patient_id):
        state = await trace.project_ingest(ctx.ui_reader, run_id)
        committed = await repo.version_for_document(ctx.ui_reader, DocumentHash(h)) is not None
        ready = ready and (committed or state.phase not in _UNSETTLED)
        doc = await repo.document(ctx.ui_reader, DocumentHash(h))
        if doc is None or not loop.needs_review(doc):
            continue
        letters.append(LetterStatus(doc.hash, doc.filename, run_id, "committed" if committed else state.phase))
        if state.phase == "awaiting_review":
            resources |= {loop._draft_from(r["draft"]).resource for r in state.review if r["decision"] != "drop"}
    current = await repo.current_version(ctx.ui_reader, patient_id)
    resources |= {f.resource for f in (current.facts if current else ()) if f.question is None}
    return IntakeStatus(tuple(letters), questionnaire.answered_by_letter(resources), ready,
                        current and replace(current, facts=()))


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


async def check_diagnosis(ctx: Ctx, patient_id: PatientId) -> DiagnosisCheck:
    """A shortlist of Condition labels stored Trials use, for the diagnosis in the Respondent's words: the latest accepted
    questionnaire's diagnosis answer, otherwise the quotes of the letters' Condition Facts (ADR 0005, ADR 0006; new
    words come with a none of these answer). It waits until every Document's Facts are committed (intake_status ready;
    NotReady before). The words are de-identified
    (deidentify_text) before the model sees them, the check stores them or the log file records them; the model sees
    only those words and the candidate labels. The check comes back `proposed` for the Respondent to answer; its
    shortlist is empty when no label fits (they can only re-word or answer not sure). What to say for each status is
    the HTTP shell's. Raises NotFound (unknown patient, or no diagnosis to check), NotReady and llm.LlmUnavailable
    (nothing stored)."""
    if not (await intake_status(ctx, patient_id)).ready:
        raise NotReady(f"patient {patient_id} has a Document whose Facts are not committed yet")
    answered = await latest_answers(ctx, patient_id)
    check = await _new_check(ctx, patient_id, (answered.answers.get("diagnosis") if answered else None)
                             or await _letter_diagnosis(ctx, patient_id))
    if check is None:
        raise NotFound(f"no diagnosis answer for patient {patient_id}")
    async with ctx.writer.transaction() as tx:
        await repo.insert_diagnosis_check(tx, check, ctx.now())
    _log_offered(check)
    return check


async def _letter_diagnosis(ctx: Ctx, patient_id: PatientId) -> str | None:
    """The quotes of the letters' Condition Facts in the current version (and of any Letter review correction made
    a Condition), in order, each once; None without any."""
    current = await repo.current_version(ctx.ui_reader, patient_id)
    corrections = next(q.ref for q in DEFINITION.questions() if q.id == questionnaire.CORRECTIONS)
    quotes = dict.fromkeys(f.quote for f in (current.facts if current else ())
                           if f.resource == FactResource.CONDITION and f.question in (None, corrections))
    return "; ".join(quotes) or None


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
                                 answer: DiagnosisAnswer) -> DiagnosisCheck:
    """The Respondent's answer to a proposed check. Ticked: one or more of its shortlist labels (equal ignoring case and
    spacing) become the patient's Condition term, which selects the Trials judged and shown. NoneOfThese: the diagnosis
    in other words starts a new check (as check_diagnosis does for the questionnaire's words), which is returned
    instead. NotSure: tell them to check with their GP; a Doctor question is raised for the diagnosis. Answered once;
    the answer and a new check are stored together or not at all. Raises NotFound (not this patient's check),
    AlreadyAnswered (the check is not awaiting an answer; checked before the labels or any model call), InvalidAnswers
    (labels missing or not in the shortlist, no new words) and, for new words, llm.LlmUnavailable (nothing stored)."""
    check = await repo.diagnosis_check(ctx.ui_reader, check_id)
    if check is None or check.patient_id != patient_id:
        raise NotFound(f"diagnosis check {check_id}")
    if check.status != "proposed":   # the transaction below re-checks, for an answer racing this one
        raise AlreadyAnswered(f"diagnosis check {check_id} is {check.status}, not awaiting an answer")
    again: DiagnosisCheck | None = None
    match answer:
        case Ticked(labels=labels):
            answered = check.tick(labels)
        case NoneOfThese(text=text):
            again = await _new_check(ctx, patient_id, text)   # before any write
            if again is None:
                raise InvalidAnswers("none of these needs the diagnosis in other words")
            answered = replace(check, status="none_of_these")
        case NotSure():
            answered = replace(check, status="not_sure")
    async with ctx.writer.transaction() as tx:
        if not await repo.answer_diagnosis_check(tx, answered, ctx.now()):
            raise AlreadyAnswered(f"diagnosis check {check_id} is not awaiting an answer")
        if again is not None:
            await repo.insert_diagnosis_check(tx, again, ctx.now())
    logfile.step(log, "record.diagnosis_check.answered", patient_id=patient_id,   # #35
                 answer={"answer": answered.status, "labels": list(answered.ticked), "text": again.text if again else None},
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


async def diagnosis_step(ctx: Ctx, patient_id: PatientId) -> DiagnosisStep:
    """Where the patient's diagnosis step stands, from the check that holds (`diagnosis`): the one place the patient's
    Condition term is read. Unfinished, with no Condition term, while nothing is settled."""
    held = await diagnosis(ctx, patient_id)
    return DiagnosisStep(held.state, held.condition_term, held.text) if held else DiagnosisStep()


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
    """Hash content, read its pages into Regions through ctx.parser, de-identify the whole Document, persist the
    document, its pages and its Regions (with boxes). Idempotent on hash (per patient): adding the same bytes twice
    returns the existing Document and does not read it again.
    De-identified text is what Citations display; raw bytes are kept only on disk (settings.raw_documents_dir).
    Raises UnreadableDocument (empty, not a PDF, or no readable text found) and NotFound before anything is stored."""
    import asyncio

    from app.record.referral import as_document, read_pdf, store_document

    await _require_patient(ctx, patient_id)
    h = storage.document_hash(patient_id, content)
    existing = await repo.document(ctx.ui_reader, h)
    if existing is not None:
        return Registered(existing, deduplicated=True)
    parsed, safe_filename = await asyncio.to_thread(read_pdf, ctx.parser, filename, content)
    now = ctx.now()
    doc = as_document(patient_id, content, safe_filename, parsed, now)
    storage.keep_raw(ctx.settings.raw_documents_dir, h, content)
    async with ctx.writer.transaction() as tx:
        await store_document(tx, doc, parsed, now)
    return Registered(doc, deduplicated=False)


@dataclass(frozen=True)
class DocumentRegions:
    """A stored Document's Regions in reading order, each with its box (fractions of the page image)."""
    document_hash: DocumentHash
    filename: str
    page_count: int
    regions: tuple[Region, ...]
    document_date: date | None = None   # read from the first page (dates.document_date); None if it gives none
    date_order: str | None = None       # "day_first" | "month_first" | None (dates.date_order)


async def document_regions(ctx: Ctx, document_hash: DocumentHash) -> DocumentRegions:
    """The de-identified Regions stored for one Document. Raises NotFound."""
    doc = await repo.document(ctx.ui_reader, document_hash)
    if doc is None:
        raise NotFound(f"document {document_hash}")
    dating = dates.dating(doc)
    return DocumentRegions(doc.hash, doc.filename, len(doc.pages), doc.regions,
                           dating.document_date.on if dating.document_date else None, dating.order)


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
    return waiting.conflicts if isinstance(waiting, AwaitingPatient) else ()


# ---- Letter review (ADR 0006) ------------------------------------------------

class NotAwaitingReview(Exception):
    """A Letter review call on a run that is not parked for one (committed, rejected, or still drafting)."""


class InvalidReview(ValueError):
    """A review answer that does not fit: no such drafted Fact, or a correction on a Fact marked "Looks right"."""


ReviewDecision = Literal["keep", "drop"]
MAX_CORRECTION = 500   # characters of what a dropped Fact should be


@dataclass(frozen=True)
class ReviewItem:
    """One drafted letter Fact in Letter review: `index` names it in answer_review; its Region is where it was read.
    Its observed-on date already follows a corrected Document date."""
    index: int
    draft: DraftFact
    region: Region | None
    decision: ReviewDecision | None     # "keep" ("Looks right"), "drop" ("Not right"), None: not answered yet
    correction: str | None              # what a dropped Fact should be, in the Respondent's words


@dataclass(frozen=True)
class LetterReview:
    """A letter's drafted Facts waiting, uncommitted, for the Respondent: flagged ones (an ambiguous or estimated
    date) first, then in reading order."""
    run_id: RunId
    document: Document
    items: tuple[ReviewItem, ...]
    document_date: date | None          # the Document date the drafts are dated by (as corrected, if it was)
    document_date_corrected: bool
    date_order: str | None


@dataclass(frozen=True)
class ReviewCommitted:
    """The letter's commit, and the questionnaire submission holding the Respondent's corrections (None without any):
    ingest it as a submitted questionnaire, so each correction becomes a Patient-reported Fact."""
    committed: Committed
    corrections: Registered | None


async def _awaiting_review(ctx: Ctx, run_id: RunId) -> tuple[Any, Document]:
    try:
        state = await trace.project_ingest(ctx.ui_reader, run_id)
    except trace.UnknownRun:
        raise NotFound(f"run {run_id}")
    if state.phase != "awaiting_review":
        raise NotAwaitingReview(f"run {run_id} is {state.phase}, not awaiting Letter review")
    log = await trace.read(ctx.ui_reader, run_id)
    started = next(e.event for e in log.events if e.event.kind == "ingest.started")
    return state, await repo.document(ctx.ui_reader, DocumentHash(started.document_hash))


async def letter_review(ctx: Ctx, run_id: RunId) -> LetterReview:
    """The drafted Facts a letter's run waits on, each beside its Region, flagged first. Raises NotFound (unknown run)
    and NotAwaitingReview."""
    state, doc = await _awaiting_review(ctx, run_id)
    dating = dates.dating(doc)
    items = []
    for i, r in enumerate(state.review):
        d = loop._draft_from(r["draft"])
        if doc.document_date is not None:
            on, flags = dates.redated(d.observed_on, d.flags, d.quote, doc.document_date)
            d = replace(d, observed_on=on, flags=flags)
        items.append(ReviewItem(i, d, doc.region(d.span_id), r["decision"], r["correction"]))
    return LetterReview(run_id, doc, tuple(sorted(items, key=lambda it: not it.draft.flagged)),
                        dating.document_date.on if dating.document_date else None, doc.document_date is not None,
                        dating.order)


async def answer_review(ctx: Ctx, run_id: RunId, index: int, decision: ReviewDecision,
                        correction: str | None = None) -> LetterReview:
    """The Respondent's word on one drafted Fact: keep ("Looks right": committed as checked) or drop ("Not right":
    never committed; `correction`, what it should be, becomes an answer in their questionnaire when the review
    commits). Answering again replaces the earlier answer. Raises NotFound, NotAwaitingReview and InvalidReview."""
    state, _ = await _awaiting_review(ctx, run_id)
    if not 0 <= index < len(state.review):
        raise InvalidReview(f"run {run_id} has no drafted Fact {index}")
    if decision not in ("keep", "drop"):
        raise InvalidReview(f"decision must be 'keep' or 'drop', got {decision!r}")
    correction = " ".join((correction or "").split()) or None
    if correction is not None and decision != "drop":
        raise InvalidReview("only a Fact marked Not right takes a correction")
    if correction is not None and len(correction) > MAX_CORRECTION:
        raise InvalidReview(f"a correction is at most {MAX_CORRECTION} characters")
    await trace.append(ctx.writer, run_id, ReviewAnswered(actor="patient", index=index, decision=decision,
                                                          correction=correction))
    return await letter_review(ctx, run_id)


async def correct_document_date(ctx: Ctx, run_id: RunId, on: date) -> LetterReview:
    """The Respondent's correction of the letter's Document date. The drafts it dated (no date of their own, or a
    relative date counted back from it) are re-dated by it when the review commits, and the review shows them so.
    Raises NotFound, NotAwaitingReview and InvalidReview (a date after today)."""
    state, doc = await _awaiting_review(ctx, run_id)
    if on > ctx.now().date():
        raise InvalidReview(f"the Document date {on.isoformat()} is after today")
    async with ctx.writer.transaction() as tx:
        await repo.set_document_date(tx, doc.hash, on)
    return await letter_review(ctx, run_id)


async def commit_review(ctx: Ctx, run_id: RunId, *, use_all_as_read: bool = False) -> ReviewCommitted:
    """Commit a letter's reviewed Facts as a new Profile version: each kept one checked, each unanswered one not
    checked, a dropped one never. With use_all_as_read every drafted Fact is committed as read, none checked, and
    the answers are set aside. The corrections of dropped Facts are added to the Respondent's latest questionnaire
    answers (the review-only question letter_corrections), registered as a new submission for the caller to ingest.
    Raises NotFound and NotAwaitingReview."""
    _, doc = await _awaiting_review(ctx, run_id)
    async with loop.patient_lock(doc.patient_id):
        state, doc = await _awaiting_review(ctx, run_id)   # again under the lock: one commit per review
        committed = await loop.commit_review(ctx, doc, run_id, state, use_all_as_read=use_all_as_read)
    said = [] if use_all_as_read else [
        questionnaire.correction_line(loop._draft_from(r["draft"]), deidentify_text(r["correction"]))
        for r in state.review if r["decision"] == "drop" and r["correction"]]
    if not said:
        return ReviewCommitted(committed, None)
    latest = await latest_answers(ctx, doc.patient_id)
    answers = dict(latest.answers) if latest else {}
    answers[questionnaire.CORRECTIONS] = questionnaire.with_corrections(answers.get(questionnaire.CORRECTIONS), said)
    return ReviewCommitted(committed, await register_questionnaire(ctx, doc.patient_id, answers,
                                                                   latest.respondent if latest else "patient"))


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
