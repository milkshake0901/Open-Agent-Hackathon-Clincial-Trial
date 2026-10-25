"""Trials from ClinicalTrials.gov (through Zetaris) and their Criteria."""
from fastapi import APIRouter, Depends

from app import record, trials
from app.api.deps import get_ctx
from app.api.schemas import ClosedTrialListOut, ClosedTrialOut
from app.ctx import Ctx

router = APIRouter(tags=["trials"])


@router.get("/patients/{pid}/closed-trials", response_model=ClosedTrialListOut)
async def closed_trials(pid: str, ctx: Ctx = Depends(get_ctx)):
    """Closed trials for the patient's confirmed Condition term, newest first; none before one is confirmed."""
    held = await record.diagnosis(ctx, record.PatientId(pid))
    term = held.condition_term if held else None
    found = await trials.closed_trials(ctx, term) if term else []
    return ClosedTrialListOut(condition_term=term, trials=[ClosedTrialOut(
        nct_id=t.nct_id, title=t.title, status=t.status, conditions=list(t.conditions), closed_on=t.closed_on,
        url=f"https://clinicaltrials.gov/study/{t.nct_id}") for t in found])


@router.post("/trials/sync")
async def sync(body: dict):
    """trials.sync(condition, location); if Trials changed and a current version exists, start a narrowed Re-scan."""
    raise NotImplementedError


@router.get("/trials")
async def list_trials(): raise NotImplementedError


@router.get("/trials/{nct}")
async def get_trial(nct: str): raise NotImplementedError
