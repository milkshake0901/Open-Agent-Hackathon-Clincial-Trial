"""A shared test step: give a patient a Condition term (ADR 0005) so a Re-scan has Trials to judge. Without one a
Re-scan judges nothing, so tests about judging tick labels first."""
from __future__ import annotations

from app import record, trials


async def tick_condition_term(ctx, patient_id, labels: list[str] | None = None):
    """Settle a Diagnosis check ticking `labels` (default: every Condition label the stored Trials use, which selects
    every Open trial). The check's two shortlist calls are answered here, whatever the fake model is scripted to say,
    and dropped from its captured calls, so a test's prompts and call counts are the Re-scan's alone."""
    fake = ctx.llm
    labels = labels if labels is not None else [one.label for one in await trials.condition_labels(ctx)]
    scripted, before = fake.responder, len(fake.calls)

    def respond(lane, system, user):
        return {"labels": labels} if "Candidate labels:" in user else {"phrases": labels}
    fake.responder = respond
    try:
        check = await record.check_diagnosis(ctx, patient_id, " and ".join(labels))
        answered = await record.answer_diagnosis_check(ctx, patient_id, check.id, "ticked", labels=labels)
    finally:
        fake.responder = scripted
        del fake.calls[before:]
    return answered
