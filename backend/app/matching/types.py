"""app/matching/types.py"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import NewType

from app.record import DocumentHash, FactId, ProfileVersionId
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


@dataclass(frozen=True)
class CriterionResult:
    criterion_id: CriterionId
    outcome: Outcome
    citation: Citation | None       # invariant (enforced by evaluator): None  <=>  outcome == UNKNOWN
    rationale: str                  # one sentence from the Matcher; shown in UI


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
    criterion_id: CriterionId
    nct_id: NctId
    subject: str      # the missing Fact subject, e.g. "ECOG performance status"
    text: str         # "Is the patient's ECOG performance status 0 or 1?"


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


@dataclass(frozen=True)
class RescanReport:
    version_id: ProfileVersionId
    run_id: RunId
    planned: tuple[NctId, ...]
    judged: tuple[NctId, ...]
    skipped_existing: tuple[NctId, ...]
    failed: tuple[tuple[NctId, str], ...]

    @classmethod
    def nothing_to_do(cls, version_id: ProfileVersionId) -> "RescanReport":
        raise NotImplementedError


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
