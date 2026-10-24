"""app/record/types.py — domain types for the patient record. No wire or row types here."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Literal, NewType

from app.trace import RunId

PatientId = NewType("PatientId", str)
DocumentHash = NewType("DocumentHash", str)      # sha256 hex of the uploaded bytes
FactId = NewType("FactId", str)
ProfileVersionId = NewType("ProfileVersionId", str)
ConflictId = NewType("ConflictId", str)
Respondent = Literal["patient", "other"]   # who answered an Intake questionnaire (GLOSSARY)


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
        which repo loads in upload order."""
        out: dict[str, Fact] = {}
        for f in self.facts:
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


@dataclass(frozen=True)
class Conflict:
    """Shown to the patient. Both sides keep provenance so the UI can show both pages."""
    id: ConflictId
    draft: DraftFact
    accepted: Fact | None          # None for IMPOSSIBLE_SEQUENCE within the same document
    message: str


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
