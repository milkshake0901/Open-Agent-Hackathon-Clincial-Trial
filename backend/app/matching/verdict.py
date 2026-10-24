"""app/matching/verdict.py — PURE verdict rules. Single source of truth for the outcome."""
from __future__ import annotations

from collections.abc import Mapping

from app.matching.types import DoctorQuestion, Outcome, RespondentQuestion, ValidatedResults, VerdictOutcome
from app.record import Question
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


def questions_from_unknowns(results: ValidatedResults, criteria: tuple[Criterion, ...], trial: Trial,
                            askable: Mapping[str, Question] = {}) -> tuple[tuple[DoctorQuestion, ...],
                                                                         tuple[RespondentQuestion, ...]]:
    """(Doctor questions, Respondent questions): exactly one of the two per UNKNOWN criterion. An unknown whose
    `ask` names a questionnaire question in `askable` (by number, "Q8") goes back to the Respondent: it turns on
    something they could know but answered vaguely or not at all. Every other unknown goes to the doctor.
    Text is templated, not model-generated, so identical Criteria on different Trials ask the same question."""
    by_id = {c.id: c for c in criteria}
    doctor, respondent = [], []
    for r in results:
        if r.outcome != Outcome.UNKNOWN:
            continue
        c = by_id[r.criterion_id]
        subject = " ".join(c.text.split()).rstrip(".")
        q = askable.get(r.ask) if r.ask else None
        if q is not None:
            respondent.append(RespondentQuestion(
                criterion_id=c.id, nct_id=trial.nct_id, question_id=q.id, question=q.ref, subject=q.label,
                text=f"Could you answer {q.ref} again, as exactly as you can? A trial needs to know: {subject}."))
        else:
            doctor.append(DoctorQuestion(criterion_id=c.id, nct_id=trial.nct_id, subject=subject,
                                         text=f"Please check against the patient's records ({c.kind} criterion): "
                                              f"{subject}."))
    return tuple(doctor), tuple(respondent)
