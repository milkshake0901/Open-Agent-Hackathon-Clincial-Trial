"""The Intake questionnaire: its definition, and submitting a completed one for a patient."""
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException

from app import matching, record
from app.api.deps import get_ctx
from app.api.schemas import LatestAnswersOut, QuestionnaireOut, QuestionnaireSubmission, RescanSummary, SubmissionAccepted
from app.ctx import Ctx

router = APIRouter(tags=["questionnaire"])


@router.get("/questionnaire/definition", response_model=QuestionnaireOut)
async def definition():
    d = record.questionnaire_definition()
    return {"version": d.version, "sections": [
        {"id": s.id, "title": s.title, "questions": [
            {"id": q.id, "number": q.number, "label": q.label, "label_other": q.label_other, "kind": q.kind,
             "options": [asdict(o) for o in q.options], "required": q.required, "help": q.help}
            for q in s.questions]}
        for s in d.sections]}


@router.get("/patients/{pid}/questionnaire", response_model=LatestAnswersOut)
async def latest(pid: str, ctx: Ctx = Depends(get_ctx)):
    """record.latest_answers: the latest accepted submission, to prefill "edit answers". 404 before the first."""
    found = await record.latest_answers(ctx, record.PatientId(pid))
    if found is None:
        raise HTTPException(404, f"no accepted questionnaire for patient {pid}")
    return LatestAnswersOut(definition_version=record.questionnaire_definition().version,
                            document_hash=found.document_hash, respondent=found.respondent, answers=found.answers)


@router.post("/patients/{pid}/questionnaire", status_code=202, response_model=SubmissionAccepted)
async def submit(pid: str, body: QuestionnaireSubmission, ctx: Ctx = Depends(get_ctx)):
    """record.submit_questionnaire, then, on Committed, a Re-scan of the new version under the same correlation id.
    Both run inline (no background jobs yet), so the response already carries the outcome and the Re-scan counts."""
    if body.definition_version != record.questionnaire_definition().version:
        raise HTTPException(422, f"questionnaire definition {body.definition_version} is out of date")
    try:
        outcome = await record.submit_questionnaire(ctx, record.PatientId(pid), body.answers, body.respondent)
    except record.InvalidAnswers as e:
        raise HTTPException(422, str(e))
    except record.NotFound as e:
        raise HTTPException(404, str(e))
    accepted = submission_accepted(outcome)
    if isinstance(outcome, record.Committed):
        report = await matching.rescan(ctx, outcome.version.id, correlation_id=outcome.run_id)
        accepted.rescan = RescanSummary(judged=len(report.judged), failed=len(report.failed))
    accepted.return_token = await record.issue_return_token(ctx, record.PatientId(pid))
    return accepted


def submission_accepted(outcome: record.IngestOutcome) -> SubmissionAccepted:
    match outcome:
        case record.Committed(run_id=run_id, version=v):
            return SubmissionAccepted(run_id=run_id, outcome="committed", document_hash=v.document_hash,
                                      profile_version_id=v.id, version_number=v.number)
        case record.AwaitingPatient(run_id=run_id):
            return SubmissionAccepted(run_id=run_id, outcome="awaiting_patient")
        case record.Rejected(run_id=run_id, reason=reason):
            return SubmissionAccepted(run_id=run_id, outcome="rejected", reason=reason)
