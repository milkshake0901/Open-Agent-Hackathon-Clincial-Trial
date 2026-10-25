"""app/api/schemas.py — wire models built FROM domain types; never imported by domain modules.
The frontend generates its TypeScript types from /openapi.json, so this is the one wire definition."""
from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel


class DocumentAccepted(BaseModel):
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

    @classmethod
    def of(cls, report: Any) -> "RescanSummary":
        """From a matching.RescanReport."""
        return cls(judged=len(report.judged), failed=len(report.failed))


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


class ConflictSideOut(BaseModel):
    """One side of a Conflict, with enough of its Document to show the page beside the other side."""
    document_hash: str
    filename: str
    page: int
    page_text: str              # de-identified
    quote: str
    value: str
    unit: str | None
    observed_on: date | None
    label: str                  # "Patient-reported, intake questionnaire, Q13" or "referral.pdf, page 2"


class ConflictOut(BaseModel):
    id: str
    message: str
    draft: ConflictSideOut               # what the new Document says
    accepted: ConflictSideOut | None     # what the record already says


class ConflictsOut(BaseModel):
    run_id: str
    conflicts: list[ConflictOut]         # empty once the run is no longer waiting on the patient


class ResolutionIn(BaseModel):
    conflict_id: str
    choice: Literal["keep_accepted", "accept_draft", "discard_both"]


class ConfirmIn(BaseModel):
    resolutions: list[ResolutionIn]


class LatestAnswersOut(BaseModel):
    """The latest accepted submission, to prefill "edit answers". Postcode and travel are never included."""
    definition_version: str
    document_hash: str
    respondent: Literal["patient", "other"]
    answers: dict[str, Any]


class QuestionnaireAccepted(DocumentAccepted):
    """Like an added Document: the Document now, its run to follow (GET /runs/{run_id}) for the outcome."""
    return_token: str | None = None   # first submission only; the frontend shows it as /return/{token}


class IngestOutcomeOut(BaseModel):
    run_id: str
    outcome: Literal["committed", "awaiting_patient", "rejected"]
    document_hash: str | None = None
    profile_version_id: str | None = None
    version_number: int | None = None
    reason: str | None = None
    rescan: RescanSummary | None = None   # set on "committed"


class SearchPreferencesIn(BaseModel):
    """As the questionnaire takes them (Q4, Q5, Q15); a field left out or blank keeps its stored value."""
    postcode: str | None = None
    max_travel_km: str | None = None    # "10" | "25" | "50" | "100" | "anywhere"
    contact: str | None = None


class SearchPreferencesOut(BaseModel):
    """What was stored, without the postcode or contact themselves: they are never sent back."""
    postcode_set: bool
    location_known: bool                # the postcode has a coarse location point, so distances can be shown
    max_travel_km: int | None           # None: no limit
    contact_set: bool


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


class RespondentQuestionOut(BaseModel):
    criterion_id: str
    nct_id: str
    question_id: str            # questionnaire question id: the web page asks it again inline
    question: str               # "Q8"
    subject: str                # the questionnaire question's wording
    text: str
    unblocks: list[str]


class SiteOut(BaseModel):
    name: str
    status: str                 # "recruiting", "not yet recruiting", ...
    km: int | None              # None: distance unknown (no or unknown postcode, or the site has no location)


class VerdictOut(BaseModel):
    nct_id: str
    title: str
    status: str
    no_longer_recruiting: bool = False    # the Trial closed after this Verdict was judged; kept, never re-judged
    profile_version_id: str
    outcome: Literal["eligible", "possible", "excluded"]
    degraded: bool
    attempts: int
    results: list[CriterionResultOut]
    questions: list[DoctorQuestionOut]
    respondent_questions: list[RespondentQuestionOut] = []
    nearest_site: SiteOut | None = None   # nearest RECRUITING site
    sites: list[SiteOut] = []             # up to 3 nearest open sites, any status
    further_away: bool = False            # no recruiting site within the travel limit: show under "Further away"


class ContactOut(BaseModel):
    name: str
    role: str                   # registry role, e.g. CONTACT, PRINCIPAL_INVESTIGATOR, SPONSOR
    email: str                  # "" when the registry gives none (likewise phone, affiliation, title)
    phone: str
    affiliation: str
    title: str


class TrialSiteOut(BaseModel):
    facility: str
    city: str
    status: str                 # registry status, e.g. RECRUITING; "" if not given
    contacts: list[ContactOut]


class TrialDetailOut(BaseModel):
    nct_id: str
    title: str
    status: str
    page_url: str                         # the Trial's ClinicalTrials.gov page
    sponsor: str                          # "" if not given
    responsible_party: ContactOut | None
    central_contacts: list[ContactOut]
    overall_officials: list[ContactOut]
    sites: list[TrialSiteOut]             # Australian Trial sites only, in registry order


class VerdictListOut(BaseModel):
    profile_version_id: str
    verdicts: list[VerdictOut]  # ranked: outcome (possible: fewest unknowns first), then nearest recruiting site


class ClosedTrialOut(BaseModel):
    """A Closed trial (ADR 0004): no Verdict, no Criterion results, only what it is and when it finished."""
    nct_id: str
    title: str
    status: str
    conditions: list[str]
    closed_on: str | None   # primary completion, else completion, else last update (ISO date)
    url: str                # its ClinicalTrials.gov page


class ClosedTrialListOut(BaseModel):
    condition_term: str | None  # None until a Diagnosis check confirms one; then `trials` is empty
    trials: list[ClosedTrialOut]  # newest first by closed_on


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
