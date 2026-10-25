"""A shared test step: give a patient a Condition term (ADR 0005) so a Re-scan has Trials to judge. Without one a
Re-scan judges nothing, so tests about judging tick labels first."""
from __future__ import annotations

from app import record, trials
from app.record import repo


async def tick_condition_term(ctx, patient_id, labels: list[str] | None = None) -> record.DiagnosisCheck:
    """Store a Diagnosis check settled as ticking `labels` (default: every Condition label the stored Trials use, which
    selects every Open trial) from a shortlist of the stored labels, as if the Respondent had ticked them; the
    Condition term spells them as the Trials do. No model is called, so a test's prompts and call counts are its own."""
    stored = await trials.condition_labels(ctx)
    offered = record.DiagnosisCheck(id=record.types.new_diagnosis_check_id(), patient_id=patient_id,
                                    text="the diagnosis", shortlist=tuple(stored), status="proposed")
    ticked = offered.tick(tuple(labels) if labels is not None else tuple(one.label for one in stored))
    async with ctx.writer.transaction() as tx:
        await repo.insert_diagnosis_check(tx, ticked, ctx.now())
    return ticked
