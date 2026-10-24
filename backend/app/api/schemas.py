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


class DiagnosisCheckIn(BaseModel):
    text: str | None = None     # a re-wording after "no"; omitted: the latest accepted diagnosis answer


class DiagnosisAnswerIn(BaseModel):
    answer: Literal["yes", "no", "not_sure"]


class DiagnosisCheckOut(BaseModel):
    """record.DiagnosisCheck. `message` is what to show the Respondent ("We understood this as ...")."""
    id: str
    text: str
    suggested_term: str | None          # None when the model was not confident enough to offer one
    confidence: float
    status: Literal["proposed", "confirmed", "rejected", "not_sure", "unclear"]
    condition: str | None               # the confirmed term that selects Trials
    needs_gp: bool                      # show the GP message; a diagnosis Doctor question is raised
    ask_again: bool                     # "no": ask the Respondent to re-word, then POST the check again
    message: str
    rescan: RescanSummary | None = None   # set when a "yes" re-scanned the current version


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
    rescan: RescanSummary | None = None   # set on "committed"
    return_token: str | None = None   # first submission only; the frontend shows it as /return/{token}


class ReturnOpened(BaseModel):
    patient_id: str
    profile_version_id: str | None    # current version, None if nothing was committed yet
    version_number: int | None


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
    criterion_id: str | None    # None (with nct_id) for a patient-level question: the diagnosis (#14)
    nct_id: str | None
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


class SubjectChangeOut(BaseModel):
    subject: str
    before: FactOut | None      # None when the subject is new in the later version
    after: FactOut


class CriterionChangeOut(BaseModel):
    criterion_id: str
    text: str
    outcome_from: Literal["met", "not_met", "unknown"] | None   # None when the Trial was not judged before
    outcome_to: Literal["met", "not_met", "unknown"]
    citation: VerdictCitationOut | None


class VerdictChangeOut(BaseModel):
    nct_id: str
    outcome_from: Literal["eligible", "possible", "excluded"] | None
    outcome_to: Literal["eligible", "possible", "excluded"]
    criteria_changed: list[CriterionChangeOut]


class VersionDiffOut(BaseModel):
    from_version: str
    to_version: str
    facts_added: list[FactOut]
    subjects_changed: list[SubjectChangeOut]
    verdicts_changed: list[VerdictChangeOut] = []   # Trials whose outcome or any Criterion result moved


# TODO: SyncReportOut, RunLogOut, TraceTreeOut, HealthOut — see docs/api.md.
