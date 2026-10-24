"""The Intake questionnaire: its definition, and submitting a completed one for a patient."""
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException

from app import record
from app.api.deps import get_ctx
from app.api.schemas import QuestionnaireOut, QuestionnaireSubmission, SubmissionAccepted
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


@router.post("/patients/{pid}/questionnaire", status_code=202, response_model=SubmissionAccepted)
async def submit(pid: str, body: QuestionnaireSubmission, ctx: Ctx = Depends(get_ctx)):
    """record.submit_questionnaire. Structured answers need no model, so #7 runs ingest inline and the
    response already carries the outcome; the background ingest → Re-scan arrives with matching (#12)."""
    if body.definition_version != record.questionnaire_definition().version:
        raise HTTPException(422, f"questionnaire definition {body.definition_version} is out of date")
    try:
        outcome = await record.submit_questionnaire(ctx, record.PatientId(pid), body.answers, body.respondent)
    except record.InvalidAnswers as e:
        raise HTTPException(422, str(e))
    except record.NotFound as e:
        raise HTTPException(404, str(e))
    accepted = _accepted(outcome)
    accepted.return_token = await record.issue_return_token(ctx, record.PatientId(pid))
    return accepted


def _accepted(outcome: record.IngestOutcome) -> SubmissionAccepted:
    match outcome:
        case record.Committed(run_id=run_id, version=v):
            return SubmissionAccepted(run_id=run_id, outcome="committed", document_hash=v.document_hash,
                                      profile_version_id=v.id, version_number=v.number)
        case record.AwaitingPatient(run_id=run_id):
            return SubmissionAccepted(run_id=run_id, outcome="awaiting_patient")
        case record.Rejected(run_id=run_id, reason=reason):
            return SubmissionAccepted(run_id=run_id, outcome="rejected", reason=reason)
