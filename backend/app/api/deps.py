"""Request helpers: the request's Ctx (built once by the lifespan in app/main.py; tests set app.state.ctx directly),
a patient's Profile version, the patient's Condition term, and the one mapping of "not found" errors to 404."""
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from app import record, trace
from app.ctx import Ctx


def get_ctx(request: Request) -> Ctx:
    return request.app.state.ctx


async def patient_version(ctx: Ctx, pid: str, vid: str) -> record.ProfileVersion:
    """The Profile version, with its Facts, if it is this patient's; 404 otherwise."""
    v = await record.profile_version(ctx, record.ProfileVersionId(vid))
    if v.patient_id != pid:
        raise HTTPException(404, f"profile version {vid}")
    return v


async def condition_term(ctx: Ctx, pid: str) -> list[str] | None:
    """The patient's Condition term (the ticked Condition labels) as the API shows it; None until some are ticked."""
    held = await record.diagnosis(ctx, record.PatientId(pid))
    return list(held.condition_term) if held and held.condition_term else None


async def not_found(request: Request, e: Exception) -> JSONResponse:
    """record.NotFound and trace.UnknownRun from any route → 404 with the error's own words (which never name
    another patient)."""
    return JSONResponse(status_code=404, content={"detail": str(e)})


EXCEPTION_HANDLERS = {record.NotFound: not_found, trace.UnknownRun: not_found}
