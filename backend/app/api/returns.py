"""The private return link: a token opens one patient's record (no accounts or passwords)."""
from fastapi import APIRouter, Depends

from app import record
from app.api.deps import get_ctx
from app.api.schemas import ReturnOpened
from app.ctx import Ctx

router = APIRouter(tags=["return"])


@router.get("/return/{token}", response_model=ReturnOpened)
async def open_return_link(token: str, ctx: Ctx = Depends(get_ctx)):
    """The patient behind the token and their current Profile version. An unknown token is a bare 404
    that says nothing about any patient."""
    patient_id = await record.patient_for_return_link(ctx, token)
    v = await record.current_version(ctx, patient_id)
    return ReturnOpened(patient_id=patient_id, profile_version_id=v.id if v else None,
                        version_number=v.number if v else None)
