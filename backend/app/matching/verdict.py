"""app/matching/verdict.py — PURE verdict rules. Single source of truth for the outcome."""
from __future__ import annotations

from app.matching.types import DoctorQuestion, Outcome, ValidatedResults, VerdictOutcome
from app.trials import Criterion, CriterionKind, Trial


def derive_outcome(results: ValidatedResults, criteria: tuple[Criterion, ...]) -> VerdictOutcome:
    """EXCLUDED if an inclusion is not met or an exclusion is met; ELIGIBLE if every inclusion is met and every
    exclusion is not met; otherwise POSSIBLE (some result is unknown)."""
    kinds = {c.id: c.kind for c in criteria}
    failing = {CriterionKind.INCLUSION: Outcome.NOT_MET, CriterionKind.EXCLUSION: Outcome.MET}
    passing = {CriterionKind.INCLUSION: Outcome.MET, CriterionKind.EXCLUSION: Outcome.NOT_MET}
    if any(r.outcome == failing[kinds[r.criterion_id]] for r in results):
        return VerdictOutcome.EXCLUDED
    if all(r.outcome == passing[kinds[r.criterion_id]] for r in results):
        return VerdictOutcome.ELIGIBLE
    return VerdictOutcome.POSSIBLE


def questions_from_unknowns(results: ValidatedResults, criteria: tuple[Criterion, ...], trial: Trial) -> tuple[DoctorQuestion, ...]:
    """One Doctor question per UNKNOWN criterion. Text is templated from the criterion, not model-generated, so
    identical Criteria on different Trials ask the same question and dedupe by subject.
    (#15 will send the ones the Respondent could answer to Respondent questions instead.)"""
    by_id = {c.id: c for c in criteria}
    out = []
    for r in results:
        if r.outcome != Outcome.UNKNOWN:
            continue
        c = by_id[r.criterion_id]
        subject = " ".join(c.text.split()).rstrip(".")
        out.append(DoctorQuestion(criterion_id=c.id, nct_id=trial.nct_id, subject=subject,
                                  text=f"Please check against the patient's records ({c.kind} criterion): {subject}."))
    return tuple(out)
