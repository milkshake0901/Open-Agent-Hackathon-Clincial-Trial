"""app/matching/types.py"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import NewType

from app.record import DiagnosisState, DocumentHash, FactId, ProfileVersionId
from app.trials import CriterionId, NctId
from app.trace import RunId


class Outcome(StrEnum):
    MET = "met"
    NOT_MET = "not_met"
    UNKNOWN = "unknown"


class VerdictOutcome(StrEnum):
    ELIGIBLE = "eligible"
    POSSIBLE = "possible"
    EXCLUDED = "excluded"


@dataclass(frozen=True)
class Citation:
    """Claim → Fact → Document page. fact_id is required: an uncited claim cannot construct one."""
    fact_id: FactId
    document_hash: DocumentHash
    page: int
    quote: str
    question: str | None = None     # "Q13" when the Fact is Patient-reported (intake questionnaire)
    filename: str | None = None     # the Document's de-identified filename, when read back from the store
    region: CitedRegion | None = None   # the letter Region the Fact was read from, with its box


@dataclass(frozen=True)
class CitedRegion:
    """Where on the page a cited letter Fact was read: its Region's span_id and box (fractions of the page image,
    origin top left), so a reason can open the page with that Region boxed."""
    span_id: str
    x0: float
    y0: float
    x1: float
    y1: float


@dataclass(frozen=True)
class CriterionResult:
    criterion_id: CriterionId
    outcome: Outcome
    citation: Citation | None       # invariant (enforced by evaluator): None  <=>  outcome == UNKNOWN
    rationale: str                  # one sentence from the Matcher; shown in UI
    ask: str | None = None          # unknown only: the questionnaire question ("Q8") the Respondent could answer
                                    # more exactly; set → a Respondent question, None → a Doctor question


@dataclass(frozen=True)
class Rejection:
    """Evaluator feedback for one result. Fed back to the Matcher verbatim."""
    criterion_id: CriterionId
    reason: str      # "fact_id F12 not in profile version", "fact 'ECOG 1' does not support 'ECOG 0 required'"


class ValidatedResults(tuple[CriterionResult, ...]):
    """Newtype: only matching.evaluator produces this. Verdict requires it, so the type system
    forbids storing results that skipped validation."""
    __slots__ = ()


@dataclass(frozen=True)
class DoctorQuestion:
    """From an unknown Criterion result on one Trial, or (criterion_id and nct_id None) patient-level: the
    diagnosis question raised when the Respondent is not sure of the diagnosis (#14), which belongs to no Criterion."""
    criterion_id: CriterionId | None
    nct_id: NctId | None
    subject: str      # the missing Fact subject, e.g. "ECOG performance status"
    text: str         # "Is the patient's ECOG performance status 0 or 1?"
    unblocks: tuple[NctId, ...] = ()   # questions_for_version: every Trial this answer would help decide


@dataclass(frozen=True)
class RespondentQuestion:
    """Sent back to the Respondent: answer a questionnaire question again, more exactly. Answering is a
    questionnaire resubmission. Deduplicated by subject (the questionnaire question) across Trials."""
    criterion_id: CriterionId
    nct_id: NctId
    question_id: str  # questionnaire question id, "treatments"
    question: str     # its number, "Q8"
    subject: str      # its wording, "What treatments have you had, and roughly when?"
    text: str
    unblocks: tuple[NctId, ...] = ()   # respondent_questions_for_version: every Trial this answer would help decide


@dataclass(frozen=True)
class TrialSiteDistance:
    """A Trial site as models and the Trials page see it: never the patient's postcode, only km from it."""
    name: str          # "Local Institution - 0439, Westmead, Australia"
    status: str        # "recruiting", "not yet recruiting", ... ("status unknown" when the registry gives none)
    km: int | None     # whole km from the patient's postcode area; None: no postcode, unknown postcode or no geoPoint


@dataclass(frozen=True)
class Verdict:
    nct_id: NctId
    profile_version_id: ProfileVersionId
    eligibility_hash: str            # which Criteria set this judged; part of the key (ADR 0002)
    outcome: VerdictOutcome          # derived, see matching.verdict.derive_outcome
    results: ValidatedResults
    questions: tuple[DoctorQuestion, ...]
    run_id: RunId
    attempts: int                    # how many Matcher attempts it took; shown in trace summary
    unsupported_downgraded: int      # claims downgraded to unknown on exhaustion
    degraded: bool                   # True when the loop hit its bound; the UI flags these Verdicts
    respondent_questions: tuple[RespondentQuestion, ...] = ()   # each unknown raises one of these or a DoctorQuestion
    # Distance (#16): filled by verdict()/verdicts_for_version() from the CURRENT search preferences, never stored,
    # never part of the outcome.
    nearest_site: TrialSiteDistance | None = None     # nearest RECRUITING site (None: the Trial lists none)
    sites: tuple[TrialSiteDistance, ...] = ()         # open sites, nearest first
    further_away: bool = False                   # beyond the travel limit: shown under "Further away", not dropped


@dataclass(frozen=True)
class ListedVerdicts:
    """The Verdicts listed for a Profile version (verdicts_for_version) and the Condition term that selected their
    Trials: None, and no Verdicts, until the patient has one (ADR 0005). `diagnosis`: where the diagnosis step stands
    (record.DiagnosisStep.state)."""
    condition_term: tuple[str, ...] | None
    verdicts: tuple[Verdict, ...]
    diagnosis: DiagnosisState = "unfinished"


@dataclass(frozen=True)
class RescanReport:
    version_id: ProfileVersionId
    run_id: RunId
    planned: tuple[NctId, ...]
    judged: tuple[NctId, ...]
    skipped_existing: tuple[NctId, ...]
    failed: tuple[tuple[NctId, str], ...]

    @classmethod
    def nothing_to_do(cls, version_id: ProfileVersionId, run_id: RunId,
                      skipped: tuple[NctId, ...] = ()) -> "RescanReport":
        return cls(version_id=version_id, run_id=run_id, planned=(), judged=(), skipped_existing=skipped, failed=())


@dataclass(frozen=True)
class CriterionChange:
    criterion_id: CriterionId
    text: str
    outcome_from: Outcome | None
    outcome_to: Outcome
    citation: Citation | None


@dataclass(frozen=True)
class VerdictChange:
    nct_id: NctId
    outcome_from: VerdictOutcome | None
    outcome_to: VerdictOutcome
    criteria_changed: tuple[CriterionChange, ...]
