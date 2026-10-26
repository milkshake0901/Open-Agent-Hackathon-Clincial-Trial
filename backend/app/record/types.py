"""app/record/types.py — domain types for the patient record. No wire or row types here."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from datetime import date
from enum import StrEnum
from typing import Literal, NewType

from app.trace import RunId
from app.trials import ConditionLabel, label_key

PatientId = NewType("PatientId", str)
DocumentHash = NewType("DocumentHash", str)      # sha256 hex identifying the Document (its bytes and patient, or a questionnaire submission)
FactId = NewType("FactId", str)
ProfileVersionId = NewType("ProfileVersionId", str)
ConflictId = NewType("ConflictId", str)
DiagnosisCheckId = NewType("DiagnosisCheckId", str)   # "dx_" + 16 hex
ReturnTokenHash = NewType("ReturnTokenHash", str)     # sha256 hex of a Return link's token; the token is never stored
Respondent = Literal["patient", "other"]   # who answered an Intake questionnaire (GLOSSARY)


def new_patient_id() -> PatientId:
    return PatientId(f"pt_{uuid.uuid4().hex[:16]}")


def new_diagnosis_check_id() -> DiagnosisCheckId:
    return DiagnosisCheckId(f"dx_{uuid.uuid4().hex[:16]}")


class FactResource(StrEnum):
    """FHIR-lite: table names after FHIR resources, only the fields we need."""
    CONDITION = "Condition"
    OBSERVATION = "Observation"
    MEDICATION_STATEMENT = "MedicationStatement"
    PROCEDURE = "Procedure"
    PATIENT = "Patient"                         # birth month, sex (ADR 0003)
    ALLERGY_INTOLERANCE = "AllergyIntolerance"


@dataclass(frozen=True)
class Page:
    number: int          # 1-based; the number a Citation shows
    text: str            # de-identified
    tables: tuple[tuple[tuple[str, ...], ...], ...] = ()   # rows of cells, for tabular blood reports


INTAKE_KINDS = frozenset({"Text", "Title", "Section-header", "List-item", "Table", "Caption"})
"""The Region kinds the Intake agent reads and a Fact can cite. Page headers, page footers and pictures (letterheads,
addresses, barcodes) are never shown to it."""


@dataclass(frozen=True)
class Region:
    """One block of a page as Nemotron Parse read it: its kind, its de-identified words and its box (fractions of the
    page image, origin top left). A Citation can point at its span_id."""
    span_id: str
    page: int
    ordinal: int
    kind: str
    text: str
    x0: float
    y0: float
    x1: float
    y1: float


@dataclass(frozen=True)
class CitedAnswer:
    """The Intake questionnaire answer a Patient-reported Fact quotes: the question's wording as the Respondent saw it,
    the whole answer, and where the quote sits in it (character offsets into `text`; None when the quote is not a
    verbatim part of the answer, as for a model's paraphrase)."""
    wording: str
    text: str
    quote_start: int | None
    quote_end: int | None


@dataclass(frozen=True)
class Document:
    hash: DocumentHash
    patient_id: PatientId
    filename: str
    pages: tuple[Page, ...]
    uploaded_at: date
    respondent: Respondent | None = None   # set only on a completed Intake questionnaire; never a Fact
    regions: tuple[Region, ...] = ()       # every page's Regions in reading order; none on a questionnaire

    def intake_regions(self, page: int) -> tuple[Region, ...]:
        """The Regions of one page the Intake agent reads and a Fact can cite (INTAKE_KINDS), in reading order."""
        return tuple(r for r in self.regions if r.page == page and r.kind in INTAKE_KINDS and r.text.strip())

    def region(self, span_id: str | None) -> Region | None:
        """The citable Region with this span_id (an INTAKE_KINDS Region of this Document), or None."""
        return next((r for r in self.regions if r.span_id == span_id and r.kind in INTAKE_KINDS), None)

    @property
    def is_questionnaire(self) -> bool:
        return self.respondent is not None


class InvalidAnswers(ValueError):
    """An answer that does not fit its question (unknown id, unknown option, malformed month), or a Diagnosis check's
    answer that does not fit the check (labels missing or not in its shortlist, no new words)."""


@dataclass(frozen=True)
class Ticked:
    """A Diagnosis check answer: these shortlist labels (equal ignoring case and spacing) are the Condition term."""
    labels: tuple[str, ...]


@dataclass(frozen=True)
class NoneOfThese:
    """A Diagnosis check answer: no shortlist label matches; `text`, the diagnosis in other words, starts a new check."""
    text: str


@dataclass(frozen=True)
class NotSure:
    """A Diagnosis check answer: check the diagnosis with the GP; a Doctor question is raised for it."""


DiagnosisAnswer = Ticked | NoneOfThese | NotSure
# "confirmed": a check confirmed under the single-term design, before Condition labels (db/migrations/0006). Invariant:
# confirmed ⇒ ticked == (), so it holds no Condition term (spec #31: the Respondent redoes the step).
DiagnosisStatus = Literal["proposed", "ticked", "none_of_these", "not_sure", "confirmed"]
# Where the patient's diagnosis step stands: ticked (a Condition term selects Trials), not_sure (it waits on the GP),
# or unfinished (nothing settled, or a check settled with no Condition term).
DiagnosisState = Literal["ticked", "not_sure", "unfinished"]

# The settling rule, in one place: which statuses settle the diagnosis (the latest settled check holds) and which of
# those leave it to the GP. "proposed" awaits an answer; "none_of_these" settles nothing: a new check is offered.
SETTLED: frozenset[DiagnosisStatus] = frozenset({"ticked", "not_sure", "confirmed"})
NEEDS_GP: frozenset[DiagnosisStatus] = frozenset({"not_sure"})


@dataclass(frozen=True)
class DiagnosisCheck:
    """A shortlist of Condition labels offered for the free-text diagnosis, and the Respondent's answer (#14, #33,
    ADR 0005). Not a Fact: the diagnosis Fact keeps the Respondent's words as its quote; the ticked labels only select
    which Trials are judged and shown. status: proposed (awaiting an answer; the shortlist may be empty when no label
    fits), ticked (one or more shortlist labels), none_of_these (a new check was offered), not_sure, or confirmed
    (DiagnosisStatus)."""
    id: DiagnosisCheckId
    patient_id: PatientId
    text: str
    shortlist: tuple[ConditionLabel, ...]     # in order of fit, at most diagnosis.SHORTLIST_SIZE
    status: DiagnosisStatus
    ticked: tuple[str, ...] = ()              # spelled as in the shortlist, in shortlist order; only when ticked

    def tick(self, labels: tuple[str, ...]) -> DiagnosisCheck:
        """This check answered with one or more of its shortlist `labels`, spelled as the shortlist spells them.
        Raises InvalidAnswers when none are given or one is not in the shortlist."""
        wanted = {label_key(label) for label in labels}
        ticked = tuple(one.label for one in self.shortlist if label_key(one.label) in wanted)
        if not wanted or len(ticked) != len(wanted):
            raise InvalidAnswers(f"tick one or more labels from diagnosis check {self.id}'s shortlist")
        return replace(self, status="ticked", ticked=ticked)

    @property
    def condition_term(self) -> tuple[str, ...] | None:
        """The Condition term: the ticked labels that select Trials; None unless some were ticked."""
        return self.ticked or None

    @property
    def settled(self) -> bool:
        """Settles the diagnosis (SETTLED): the latest settled check is the one that holds."""
        return self.status in SETTLED

    @property
    def needs_gp(self) -> bool:
        """Tell the Respondent to check with their GP; a Doctor question is raised for the diagnosis."""
        return self.status in NEEDS_GP

    @property
    def state(self) -> DiagnosisState:
        """The diagnosis step's state while this check holds."""
        return "ticked" if self.condition_term else "not_sure" if self.needs_gp else "unfinished"


@dataclass(frozen=True)
class DiagnosisStep:
    """Where the patient's diagnosis step stands, from the check that holds (record.diagnosis): its state, the
    Condition term that selects Trials (None unless ticked) and the Respondent's words for the diagnosis."""
    state: DiagnosisState = "unfinished"
    condition_term: tuple[str, ...] | None = None
    text: str = ""


@dataclass(frozen=True)
class SearchPreferences:
    """Kept on the patient, never as Facts (ADR 0003): never rendered into a Document, never in a prompt.
    The postcode is turned into a coarse location point when it is stored; code measures distances from that
    point (#16); models see only "site name, status, km"."""
    postcode: str | None
    max_travel_km: int | None        # None: no limit ("anywhere", or not answered)
    contact: str | None              # optional email or phone for "you have new questions" notices
    location: tuple[float, float] | None = None   # the postcode's coarse point, computed when it is stored;
                                                  # None: no postcode, or one not in the table


@dataclass(frozen=True)
class DraftFact:
    """What Intake proposes. Not a Fact until the critic accepts and the loop commits.
    Invariant encoded in critic: a DraftFact with page outside the Document is Retryable."""
    resource: FactResource
    subject: str          # normalised, e.g. "EGFR mutation", "haemoglobin", "pembrolizumab"
    value: str            # "positive", "11.2", "started"
    unit: str | None
    observed_on: date | None   # None is a Retryable finding, never stored
    page: int
    quote: str            # verbatim span from the page; evaluator and UI use it
    question: str | None = None   # "Q3" when drafted from an Intake questionnaire answer
    span_id: str | None = None    # the Region the quote was read from (a letter); page is that Region's page


@dataclass(frozen=True)
class Fact:
    """Accepted, append-only. Same shape as DraftFact plus identity and provenance."""
    id: FactId
    document_hash: DocumentHash
    page: int
    resource: FactResource
    subject: str
    value: str
    unit: str | None
    observed_on: date
    quote: str
    question: str | None = None   # "Q3": Patient-reported Facts cite "intake questionnaire, Q3"
    span_id: str | None = None    # the Region the quote was read from; None for a questionnaire or an older Fact


@dataclass(frozen=True)
class ProfileVersion:
    id: ProfileVersionId
    patient_id: PatientId
    number: int                   # 1, 2, 3... per patient; UI says "v3"
    document_hash: DocumentHash   # the Document whose acceptance created this version
    fact_ids: frozenset[FactId]
    facts: tuple[Fact, ...] = ()  # loaded on demand; empty in list views

    def current(self) -> dict[str, Fact]:
        """subject → Fact with latest observed_on (ADR 0002). Pure; ties go to the later Fact in `facts`,
        which repo loads in the order their Documents were accepted.
        Among Patient-reported Facts for one subject, the later submission supersedes the earlier one whatever
        their observed-on dates (a resubmission is a correction: ADR 0002 amendment); only the latest takes part."""
        latest_reported = {f.subject: f for f in self.facts if f.question is not None}
        out: dict[str, Fact] = {}
        for f in self.facts:
            if f.question is not None and latest_reported[f.subject] is not f:
                continue
            if f.subject not in out or f.observed_on >= out[f.subject].observed_on:
                out[f.subject] = f
        return out


# ---- critic findings -------------------------------------------------------

class FindingKind(StrEnum):
    # Retryable: Intake can fix by re-reading the Document with feedback.
    MISSING_DATE = "missing_date"
    BAD_PAGE = "bad_page"
    QUOTE_NOT_ON_PAGE = "quote_not_on_page"
    UNKNOWN_REGION = "unknown_region"                # a letter's draft names no citable Region of the Document
    UNIT_OUT_OF_RANGE = "unit_out_of_range"
    DUPLICATE_OF_ACCEPTED = "duplicate_of_accepted"
    # Conflict: contradicts the accepted record; only the patient can resolve.
    CONTRADICTS_ACCEPTED = "contradicts_accepted"
    IMPOSSIBLE_SEQUENCE = "impossible_sequence"      # e.g. age decreasing, procedure before diagnosis


@dataclass(frozen=True)
class Finding:
    kind: FindingKind
    draft_index: int
    message: str
    severity: Literal["retryable", "conflict"]   # derived from kind; the loop branches on this only
    accepted_fact_id: FactId | None = None       # CONTRADICTS_ACCEPTED: the accepted Fact on the other side


@dataclass(frozen=True)
class Conflict:
    """Shown to the patient. Both sides keep provenance so the UI can show both pages."""
    id: ConflictId
    draft: DraftFact
    accepted: Fact | None          # None for IMPOSSIBLE_SEQUENCE within the same document
    message: str
    document_hash: DocumentHash | None = None   # the Document the draft was read from (the run's Document)


@dataclass(frozen=True)
class Resolution:
    conflict_id: ConflictId
    choice: Literal["keep_accepted", "accept_draft", "discard_both"]


# ---- loop outcomes (exhaustive union) --------------------------------------

@dataclass(frozen=True)
class Committed:
    run_id: RunId
    version: ProfileVersion


@dataclass(frozen=True)
class AwaitingPatient:
    run_id: RunId
    conflicts: tuple[Conflict, ...]


@dataclass(frozen=True)
class Rejected:
    run_id: RunId
    reason: str


IngestOutcome = Committed | AwaitingPatient | Rejected


@dataclass(frozen=True)
class VersionDiff:
    from_version: ProfileVersionId
    to_version: ProfileVersionId
    facts_added: tuple[Fact, ...]
    subjects_changed: tuple[tuple[str, Fact | None, Fact], ...]   # (subject, before, after)
