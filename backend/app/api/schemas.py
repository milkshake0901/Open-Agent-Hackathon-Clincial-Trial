"""app/api/schemas.py — wire models built FROM domain types; never imported by domain modules.
The frontend generates its TypeScript types from /openapi.json, so this is the one wire definition."""
from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from app.enquiry import EnquiryKind


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


class TickedIn(BaseModel):
    answer: Literal["ticked"]
    labels: list[str] = Field(min_length=1)   # one or more labels from the check's shortlist


class NoneOfTheseIn(BaseModel):
    answer: Literal["none_of_these"]
    text: str                   # the diagnosis in other words, which start a new check (returned instead)


class NotSureIn(BaseModel):
    answer: Literal["not_sure"]


DiagnosisAnswerIn = Annotated[TickedIn | NoneOfTheseIn | NotSureIn, Field(discriminator="answer")]


class ConditionLabelOut(BaseModel):
    """trials.ConditionLabel: a Condition label and how many stored Open and Closed trials list it."""
    label: str
    open: int
    closed: int


class DiagnosisCheckOut(BaseModel):
    """record.DiagnosisCheck. `message` is what to show the Respondent ("Tick the conditions that match ...")."""
    id: str
    text: str
    shortlist: list[ConditionLabelOut]   # offered labels, best fit first; empty when none fit
    ticked: list[str]                   # status ticked: the Condition term, the labels that select Trials; else []
    status: Literal["proposed", "ticked", "not_sure"]   # none of these returns the new check, proposed
    needs_gp: bool                      # show the GP message; a diagnosis Doctor question is raised
    message: str
    rescan: RescanSummary | None = None   # set when ticking labels re-scanned the current version


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
    span_id: str | None = None  # the Region of a letter the quote was read from (GET /documents/{hash}/regions)
    label: str                  # "Patient-reported, intake questionnaire, Q3" or "page 2"


class FactOut(BaseModel):
    id: str
    resource: str
    subject: str
    value: str
    unit: str | None
    observed_on: date
    citation: CitationOut
    flags: list[str] = []       # how observed_on was settled: ambiguous_date, estimated_date, document_date
    flagged: bool = False       # the date is ambiguous or an estimate: Letter review shows it first


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
    filename: str | None = None # the Document's de-identified filename
    region: "CitationRegionOut | None" = None   # a letter Fact's Region: the page image with this box opens it


class CitationRegionOut(BaseModel):
    """A Region's span_id and box: fractions of GET /documents/{hash}/pages/{page}/image, origin top left."""
    span_id: str
    x0: float
    y0: float
    x1: float
    y1: float


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


class OutcomeMeasureOut(BaseModel):
    measure: str
    description: str            # "" when the registry gives none (likewise time_frame)
    time_frame: str


class ResultValueOut(BaseModel):
    group: str                  # the arm or group's title
    value: str
    spread: str                 # "" when the registry gives none (likewise lower, upper)
    lower: str
    upper: str
    label: str                  # class and category the value is for when the measure is split; "" otherwise


class PostedResultOut(BaseModel):
    type: str                   # PRIMARY, SECONDARY, OTHER_PRE_SPECIFIED or POST_HOC
    title: str
    description: str
    time_frame: str
    unit: str
    param_type: str             # e.g. MEDIAN, MEAN, COUNT_OF_PARTICIPANTS
    values: list[ResultValueOut]


class PublicationOut(BaseModel):
    pmid: str                   # "" when the registry gives only a citation
    type: str                   # RESULT, BACKGROUND or DERIVED
    citation: str
    url: str                    # PubMed page; "" without a PubMed id


class OutcomesOut(BaseModel):
    primary: list[OutcomeMeasureOut]
    secondary: list[OutcomeMeasureOut]
    other: list[OutcomeMeasureOut]
    has_results: bool
    results: list[PostedResultOut]
    publications: list[PublicationOut]


class OutcomeSummaryOut(BaseModel):
    nct_id: str
    summary: str                # plain-language summary of the Trial's Outcomes (#26), written on first open


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
    outcomes: OutcomesOut                 # what it measured or found (#25)


class EnquiryIn(BaseModel):
    include: list[str]                    # ids of the clinical details the Respondent confirmed (from GET .../enquiry)


class ClinicalDetailOut(BaseModel):
    id: str
    label: str
    text: str                             # de-identified
    included: bool                        # in this draft; an unticked one never reached the model


class RecipientOut(BaseModel):
    name: str
    email: str
    kind: Literal["site", "central", "responsible_party", "official"]
    facility: str | None


class EnquiryDetailsOut(BaseModel):
    """What an Enquiry may include, shown to the Respondent (all ticked) before anything is drafted."""
    nct_id: str
    details: list[ClinicalDetailOut]


class EnquiryOut(BaseModel):
    nct_id: str
    template: EnquiryKind
    subject: str
    body: str                             # name and contact are placeholders the Respondent fills in
    recipient: RecipientOut | None        # None: the Trial lists no email; see sponsor
    sponsor: str
    details: list[ClinicalDetailOut]


class VerdictListOut(BaseModel):
    profile_version_id: str
    condition_term: list[str] | None  # the ticked Condition labels; None (and `verdicts` empty) until some are ticked
    diagnosis: Literal["ticked", "not_sure", "unfinished"]   # the diagnosis step: labels ticked (`condition_term`),
                                                             # answered not sure (it waits on the GP), or neither yet
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
    condition_term: list[str] | None  # the ticked Condition labels; None (and `trials` empty) until some are ticked
    trials: list[ClosedTrialOut]  # newest first by closed_on


class LetterOut(BaseModel):
    patient_id: str
    document_hash: str
    filename: str
    answers: dict[str, str] = {}


class LetterListOut(BaseModel):
    letters: list[LetterOut]


class MatchingTrialsOut(BaseModel):
    """Stored trials whose Condition labels contain one of the search phrases, open first."""
    labels: list[str]
    open: list[ClosedTrialOut]
    closed: list[ClosedTrialOut]


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


class AskIn(BaseModel):
    question: str


class RegionOut(BaseModel):
    span_id: str
    page: int
    ordinal: int
    kind: str
    text: str
    x0: float
    y0: float
    x1: float
    y1: float


class DocumentRegionsOut(BaseModel):
    document_hash: str
    filename: str
    page_count: int
    regions: list[RegionOut]
    document_date: date | None = None   # the Document date read from its first page (GLOSSARY); None if it gives none
    date_order: Literal["day_first", "month_first"] | None = None   # how it writes numeric dates; None: not settled


class GroundedCitationOut(BaseModel):
    span_id: str
    document_hash: str
    filename: str
    page: int
    quote: str
    x0: float
    y0: float
    x1: float
    y1: float


class AskOut(BaseModel):
    answer: Literal["yes", "no", "unknown"]
    reasoning: str
    as_of: date
    patient_label: str
    document_hash: str
    filename: str
    page_count: int
    citations: list[GroundedCitationOut]


class ScreenIn(BaseModel):
    nct_ids: list[str]


class CriterionScreenOut(BaseModel):
    criterion_id: str
    kind: Literal["inclusion", "exclusion"]
    text: str
    outcome: Literal["met", "not_met", "unknown"]
    rationale: str
    span_id: str | None
    page: int | None
    quote: str | None
    x0: float | None
    y0: float | None
    x1: float | None
    y1: float | None


class TrialScreenOut(BaseModel):
    nct_id: str
    title: str
    outcome: Literal["eligible", "possible", "excluded"]
    criteria: list[CriterionScreenOut]


class TrialAskIn(BaseModel):
    question: str


class TrialAskCitationOut(BaseModel):
    span_id: str
    document_hash: str
    filename: str
    page: int
    quote: str
    x0: float
    y0: float
    x1: float
    y1: float


class CriterionMissOut(BaseModel):
    criterion_id: str
    clause: str
    why: str
    citation: TrialAskCitationOut


class TrialAskOut(BaseModel):
    nct_id: str
    title: str
    question: str
    standing: Literal["eligible", "possible", "excluded", "needs_information"]
    answer: str
    to_gather: list[str]
    citations: list[TrialAskCitationOut]
    misses: list[CriterionMissOut]
    via: Literal["zetaris", "postgres"]


# TODO: RunLogOut, TraceTreeOut, HealthOut — see docs/api.md.
