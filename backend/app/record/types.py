"""app/record/types.py — domain types for the patient record. No wire or row types here."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Literal, NewType

from app.trace import RunId

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


@dataclass(frozen=True)
class Document:
    hash: DocumentHash
    patient_id: PatientId
    filename: str
    pages: tuple[Page, ...]
    uploaded_at: date
    respondent: Respondent | None = None   # set only on a completed Intake questionnaire; never a Fact

    @property
    def is_questionnaire(self) -> bool:
        return self.respondent is not None


DiagnosisAnswer = Literal["yes", "no", "not_sure"]
DiagnosisStatus = Literal["proposed", "confirmed", "rejected", "not_sure", "unclear"]

# The settling rule, in one place: the status each answer gives a proposed check, and which statuses settle the
# diagnosis (the latest settled check holds) and which of those leave it to the GP. "proposed" awaits an answer;
# "rejected" ("no") settles nothing: the Respondent is asked again.
ANSWER_STATUS: dict[DiagnosisAnswer, DiagnosisStatus] = {"yes": "confirmed", "no": "rejected", "not_sure": "not_sure"}
SETTLED: frozenset[DiagnosisStatus] = frozenset({"confirmed", "not_sure", "unclear"})
NEEDS_GP: frozenset[DiagnosisStatus] = frozenset({"not_sure", "unclear"})


@dataclass(frozen=True)
class DiagnosisCheck:
    """A condition term proposed for the free-text diagnosis, and the Respondent's answer (#14). Not a Fact: the
    diagnosis Fact keeps the Respondent's words as its quote; a confirmed term only selects which Trials are judged.
    status: proposed (awaiting yes / no / not sure), confirmed, rejected ("no": ask again), not_sure, or unclear
    (the model could not propose a term with confidence, so none was offered)."""
    id: DiagnosisCheckId
    patient_id: PatientId
    text: str
    suggested_term: str | None
    confidence: float
    status: DiagnosisStatus

    @property
    def condition_term(self) -> str | None:
        """The confirmed Condition term that drives Trial selection; None unless confirmed."""
        return self.suggested_term if self.status == "confirmed" else None

    @property
    def settled(self) -> bool:
        """Settles the diagnosis (SETTLED): the latest settled check is the one that holds."""
        return self.status in SETTLED

    @property
    def needs_gp(self) -> bool:
        """Tell the Respondent to check with their GP; a Doctor question is raised for the diagnosis."""
        return self.status in NEEDS_GP

    @property
    def ask_again(self) -> bool:
        return self.status == "rejected"


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
