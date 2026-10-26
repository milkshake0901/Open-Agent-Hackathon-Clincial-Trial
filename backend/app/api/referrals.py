"""Load a referral letter and fill Intake answers from the regions the parse model read."""
from fastapi import APIRouter, Depends, HTTPException, UploadFile

from app import record
from app.api.deps import get_ctx
from app.api.schemas import LetterListOut, LetterOut
from app.ctx import Ctx

router = APIRouter(tags=["referrals"])

MAX_LETTER_BYTES = 20 * 1024 * 1024


def _out(letter: record.LetterPrefill) -> LetterOut:
    return LetterOut(patient_id=letter.patient_id, document_hash=letter.document_hash,
                     filename=letter.filename, answers=letter.answers)


@router.get("/referrals", response_model=LetterListOut)
async def list_referrals(ctx: Ctx = Depends(get_ctx)):
    """Referral letters that already have parsed regions."""
    return LetterListOut(letters=[_out(letter) for letter in await record.referral_letters(ctx)])


@router.post("/patients/{pid}/referral/prefill", response_model=LetterOut)
async def prefill_referral(pid: str, ctx: Ctx = Depends(get_ctx)):
    """Fill Intake answers from this patient's stored letter. Does not call the parse model again."""
    try:
        return _out(await record.prefill_letter(ctx, record.PatientId(pid)))
    except record.NotFound as e:
        raise HTTPException(404, str(e)) from e


@router.post("/referrals", response_model=LetterOut)
async def load_referral(file: UploadFile, ctx: Ctx = Depends(get_ctx)):
    """Read one referral PDF, keep its regions, and fill the Intake answers those regions support."""
    content = await file.read(MAX_LETTER_BYTES + 1)
    if len(content) > MAX_LETTER_BYTES:
        raise HTTPException(413, "the file is larger than 20 MB")
    try:
        return _out(await record.load_letter(ctx, file.filename or "referral.pdf", content))
    except record.UnreadableDocument as e:
        raise HTTPException(422, str(e)) from e
