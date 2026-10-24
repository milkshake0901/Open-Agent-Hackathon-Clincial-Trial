"""app/api/schemas.py — wire models built FROM domain types; never imported by domain modules.
The frontend generates its TypeScript types from /openapi.json, so this is the one wire definition."""
from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel


class UploadAccepted(BaseModel):
    document_hash: str
    run_id: str
    deduplicated: bool


class RunAccepted(BaseModel):
    run_id: str


class OptionOut(BaseModel):
    value: str
    label: str


class QuestionOut(BaseModel):
    id: str
    number: int                 # cited as "Q<number>"
    label: str                  # "your" wording, when the patient answers
    label_other: str            # "their" wording, when someone answers on the patient's behalf
    kind: Literal["month_year", "single", "multi", "text", "textarea", "repeat"]
    options: list[OptionOut]
    required: bool
    help: str | None


class SectionOut(BaseModel):
    id: str
    title: str
    questions: list[QuestionOut]


class QuestionnaireOut(BaseModel):
    version: str
    sections: list[SectionOut]


class QuestionnaireSubmission(BaseModel):
    definition_version: str
    respondent: Literal["patient", "other"]
    answers: dict[str, Any]     # question id → value; month_year is "YYYY-MM", single is an option value


class LatestAnswersOut(BaseModel):
    """The latest accepted submission, to prefill "edit answers". Postcode and travel are never included."""
    definition_version: str
    document_hash: str
    respondent: Literal["patient", "other"]
    answers: dict[str, Any]


class SubmissionAccepted(BaseModel):
    run_id: str
    outcome: Literal["committed", "awaiting_patient", "rejected"]
    document_hash: str | None = None
    profile_version_id: str | None = None
    version_number: int | None = None
    reason: str | None = None


class PatientIn(BaseModel):
    label: str


class PatientCreated(BaseModel):
    patient_id: str


class CitationOut(BaseModel):
    document_hash: str
    page: int
    quote: str
    label: str                  # "Patient-reported, intake questionnaire, Q3" or "page 2"


class FactOut(BaseModel):
    id: str
    resource: str
    subject: str
    value: str
    unit: str | None
    observed_on: date
    citation: CitationOut


class VersionOut(BaseModel):
    id: str
    number: int
    document_hash: str
    facts: list[FactOut]
    current: dict[str, str]     # subject → fact id


class SubjectChangeOut(BaseModel):
    subject: str
    before: FactOut | None      # None when the subject is new in the later version
    after: FactOut


class VersionDiffOut(BaseModel):
    from_version: str
    to_version: str
    facts_added: list[FactOut]
    subjects_changed: list[SubjectChangeOut]   # verdicts_changed arrives with matching (#12)


# TODO: VerdictSummaryOut, VerdictOut, VerdictChangeOut,
#       DoctorQuestionOut, SyncReportOut, RunLogOut, TraceTreeOut, HealthOut — see docs/api.md.
