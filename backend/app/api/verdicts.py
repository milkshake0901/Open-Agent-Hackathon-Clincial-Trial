"""Verdicts, why they changed, and Doctor questions."""
from fastapi import APIRouter

router = APIRouter(tags=["verdicts"])


@router.post("/patients/{pid}/versions/{vid}/rescan", status_code=202)
async def rescan(pid: str, vid: str):
    """Idempotent: finishes immediately with everything skipped if nothing changed."""
    raise NotImplementedError


@router.get("/patients/{pid}/versions/{vid}/verdicts")
async def list_verdicts(pid: str, vid: str):
    """Ranked: eligible, then possible (fewest unknowns first), then excluded."""
    raise NotImplementedError


@router.get("/patients/{pid}/versions/{vid}/verdicts/{nct}")
async def get_verdict(pid: str, vid: str, nct: str): raise NotImplementedError


@router.get("/patients/{pid}/versions/{vid}/verdicts/{nct}/change")
async def verdict_change(pid: str, vid: str, nct: str, from_: str): raise NotImplementedError


@router.get("/patients/{pid}/questions")
async def doctor_questions(pid: str, version: str): raise NotImplementedError
