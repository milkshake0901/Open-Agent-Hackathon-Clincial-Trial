"""Trials from ClinicalTrials.gov (through Zetaris) and their Criteria."""
from fastapi import APIRouter

router = APIRouter(tags=["trials"])


@router.post("/trials/sync")
async def sync(body: dict):
    """trials.sync(condition, location); if Trials changed and a current version exists, start a narrowed Re-scan."""
    raise NotImplementedError


@router.get("/trials")
async def list_trials(): raise NotImplementedError


@router.get("/trials/{nct}")
async def get_trial(nct: str): raise NotImplementedError
