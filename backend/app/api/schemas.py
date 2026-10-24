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


class RescanSummary(BaseModel):
    judged: int                 # Trials given a Verdict by the Re-scan that followed the commit
    failed: int                 # Trials left without one (model unavailable); the next Re-scan retries them


class SubmissionAccepted(BaseModel):
    run_id: str
    outcome: Literal["committed", "awaiting_patient", "rejected"]
    document_hash: str | None = None
    profile_version_id: str | None = None
    version_number: int | None = None
    reason: str | None = None
    rescan: RescanSummary | None = None   # set on "committed"


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


class VerdictCitationOut(BaseModel):
    fact_id: str
    document_hash: str
    page: int
    quote: str
    question: str | None        # "Q13" for a Patient-reported Fact: the web page links to that question
    label: str                  # "Patient-reported, intake questionnaire, Q13" or "page 2"


class CriterionResultOut(BaseModel):
    criterion_id: str
    kind: Literal["inclusion", "exclusion"]
    text: str
    outcome: Literal["met", "not_met", "unknown"]
    rationale: str
    citation: VerdictCitationOut | None


class DoctorQuestionOut(BaseModel):
    criterion_id: str
    nct_id: str
    subject: str
    text: str
    unblocks: list[str]


class VerdictOut(BaseModel):
    nct_id: str
    title: str
    status: str
    profile_version_id: str
    outcome: Literal["eligible", "possible", "excluded"]
    degraded: bool
    attempts: int
    results: list[CriterionResultOut]
    questions: list[DoctorQuestionOut]


class VerdictListOut(BaseModel):
    profile_version_id: str
    verdicts: list[VerdictOut]  # ranked: eligible, possible (fewest unknowns first), excluded


class RescanOut(BaseModel):
    run_id: str
    planned: list[str]
    judged: list[str]
    skipped_existing: list[str]
    failed: list[list[str]]     # [nct_id, reason]


# TODO: VerdictChangeOut, SyncReportOut, RunLogOut, TraceTreeOut, HealthOut — see docs/api.md.
