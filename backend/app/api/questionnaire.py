"""The Intake questionnaire: its definition, and submitting a completed one for a patient."""
from dataclasses import asdict

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from app import llm, matching, record
from app.api.deps import get_ctx
from app.api.documents import start_ingest
from app.api.schemas import (
    DiagnosisAnswerIn, DiagnosisCheckIn, DiagnosisCheckOut, LatestAnswersOut, QuestionnaireAccepted, QuestionnaireOut,
    QuestionnaireSubmission, RescanSummary,
)
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


@router.post("/patients/{pid}/questionnaire", status_code=202, response_model=QuestionnaireAccepted)
async def submit(pid: str, body: QuestionnaireSubmission, background: BackgroundTasks, ctx: Ctx = Depends(get_ctx)):
    """record.register_questionnaire → 202 {document_hash, run_id, deduplicated, return_token}; background:
    record.ingest → on Committed, matching.rescan with the same correlation id, exactly like an upload. The UI
    follows the run (GET /runs/{run_id}) to its outcome."""
    if body.definition_version != record.questionnaire_definition().version:
        raise HTTPException(422, f"questionnaire definition {body.definition_version} is out of date")
    try:
        registered = await record.register_questionnaire(ctx, record.PatientId(pid), body.answers, body.respondent)
    except record.InvalidAnswers as e:
        raise HTTPException(422, str(e))
    except record.NotFound as e:
        raise HTTPException(404, str(e))
    run_id = await start_ingest(ctx, background, registered)
    return QuestionnaireAccepted(document_hash=registered.document.hash, run_id=run_id,
                                 deduplicated=registered.deduplicated,
                                 return_token=await record.issue_return_token(ctx, record.PatientId(pid)))


def _check_out(c: record.DiagnosisCheck, rescan: RescanSummary | None = None) -> DiagnosisCheckOut:
    return DiagnosisCheckOut(id=c.id, text=c.text, suggested_term=c.suggested_term, confidence=c.confidence,
                             status=c.status, condition=c.condition, needs_gp=c.needs_gp, ask_again=c.ask_again,
                             message=c.message, rescan=rescan)


@router.post("/patients/{pid}/questionnaire/diagnosis-check", status_code=201, response_model=DiagnosisCheckOut)
async def diagnosis_check(pid: str, body: DiagnosisCheckIn, ctx: Ctx = Depends(get_ctx)):
    """record.check_diagnosis: a proposed condition term for the Respondent to answer, or (unclear) the GP message.
    404: unknown patient or no diagnosis answer yet; 503: model unavailable (nothing stored)."""
    try:
        return _check_out(await record.check_diagnosis(ctx, record.PatientId(pid), body.text))
    except record.NotFound as e:
        raise HTTPException(404, str(e))
    except llm.LlmUnavailable as e:
        raise HTTPException(503, str(e))


@router.post("/patients/{pid}/questionnaire/diagnosis-check/{check_id}", response_model=DiagnosisCheckOut)
async def answer_diagnosis_check(pid: str, check_id: str, body: DiagnosisAnswerIn, ctx: Ctx = Depends(get_ctx)):
    """record.answer_diagnosis_check. A "yes" re-scans the current version inline, so Trials the confirmed term
    selects get a Verdict. 404: not this patient's check; 409: already answered (or unclear)."""
    patient_id = record.PatientId(pid)
    try:
        check = await record.answer_diagnosis_check(ctx, patient_id, check_id, body.answer)
    except record.NotFound as e:
        raise HTTPException(404, str(e))
    except record.InvalidAnswers as e:
        raise HTTPException(409, str(e))
    summary = None
    if check.condition is not None and (current := await record.current_version(ctx, patient_id)) is not None:
        report = await matching.rescan(ctx, current.id)
        summary = RescanSummary(judged=len(report.judged), failed=len(report.failed))
    return _check_out(check, summary)
