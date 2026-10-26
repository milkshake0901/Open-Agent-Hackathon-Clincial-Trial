"""Fill Intake answers from the Regions of a letter already added to the patient (until the short questionnaire, #49)."""
from fastapi import APIRouter, Depends, HTTPException

from app import record
from app.api.deps import get_ctx
from app.api.schemas import LetterOut
from app.ctx import Ctx

router = APIRouter(tags=["referrals"])


def _out(letter: record.LetterPrefill) -> LetterOut:
    return LetterOut(patient_id=letter.patient_id, document_hash=letter.document_hash,
                     filename=letter.filename, answers=letter.answers)


@router.post("/patients/{pid}/referral/prefill", response_model=LetterOut)
async def prefill_referral(pid: str, ctx: Ctx = Depends(get_ctx)):
    """Fill Intake answers from this patient's stored letter. Does not call the parse model again."""
    try:
        return _out(await record.prefill_letter(ctx, record.PatientId(pid)))
    except record.NotFound as e:
        raise HTTPException(404, str(e)) from e
