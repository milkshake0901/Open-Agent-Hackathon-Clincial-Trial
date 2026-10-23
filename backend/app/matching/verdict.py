"""app/matching/verdict.py — PURE verdict rules. Single source of truth for the outcome."""
from __future__ import annotations

from app.matching.types import DoctorQuestion, Outcome, ValidatedResults, VerdictOutcome
from app.trials import Criterion, CriterionKind, Trial


def derive_outcome(results: ValidatedResults, criteria: tuple[Criterion, ...]) -> VerdictOutcome:
    """# TODO
    #   by_id = {c.id: c for c in criteria}
    #   if any(inclusion NOT_MET) or any(exclusion MET): EXCLUDED
    #   elif all(inclusion MET) and all(exclusion NOT_MET): ELIGIBLE
    #   else: POSSIBLE   (some UNKNOWN)
    """
    raise NotImplementedError


def questions_from_unknowns(results: ValidatedResults, criteria: tuple[Criterion, ...], trial: Trial) -> tuple[DoctorQuestion, ...]:
    """One question per UNKNOWN criterion. Text is templated from the criterion, not model-generated:
    'Does the patient meet: <criterion text>?' — deterministic so questions dedupe across Trials by subject."""
    raise NotImplementedError
