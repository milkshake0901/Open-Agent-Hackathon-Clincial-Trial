"""Recruiting trials from ClinicalTrials.gov, and a screen of those trials against a parsed letter."""
from fastapi import APIRouter, Depends, HTTPException

from app import matching, trials
from app.api.deps import get_ctx
from app.api.schemas import (
    CriterionScreenOut, ScreenIn, TrialScreenOut, TrialSyncIn, TrialSyncOut,
)
from app.ctx import Ctx
from app.llm import LlmUnavailable

router = APIRouter(tags=["trials"])


@router.post("/trials/sync", response_model=TrialSyncOut)
async def sync_trials(body: TrialSyncIn, ctx: Ctx = Depends(get_ctx)):
    """Recruiting studies for a condition and a place. Prior drugs are not part of the query."""
    condition = " ".join(body.condition.split())
    location = " ".join(body.location.split())
    if not condition:
        raise HTTPException(422, "the condition is empty")
    if body.max_trials < 1 or body.max_trials > 20:
        raise HTTPException(422, "max_trials is between 1 and 20")
    try:
        report = await trials.sync(ctx, condition, location, max_trials=body.max_trials)
    except trials.TrialsUnavailable as e:
        raise HTTPException(502, str(e)) from e
    return TrialSyncOut(fetched=report.fetched, new=list(report.new), changed=list(report.changed),
                        unchanged=list(report.unchanged), source=report.source)


@router.post("/patients/{pid}/trials/screen", response_model=list[TrialScreenOut])
async def screen_trials(pid: str, body: ScreenIn, ctx: Ctx = Depends(get_ctx)):
    """Judge these trials' criteria against the patient's letter. Each decisive answer names a region."""
    if not body.nct_ids:
        raise HTTPException(422, "name the trials to screen")
    if len(body.nct_ids) > 5:
        raise HTTPException(422, "screen at most 5 trials at a time")
    try:
        screens = await matching.screen_letter(ctx, pid, body.nct_ids)
    except LlmUnavailable as e:
        raise HTTPException(503, str(e)) from e
    return [TrialScreenOut(
        nct_id=screen.nct_id, title=screen.title, outcome=screen.outcome,
        criteria=[CriterionScreenOut(
            criterion_id=row.criterion_id, kind=row.kind, text=row.text, outcome=row.outcome,
            rationale=row.rationale, span_id=row.span_id, page=row.page, quote=row.quote,
            x0=row.x0, y0=row.y0, x1=row.x1, y1=row.y1,
        ) for row in screen.criteria],
    ) for screen in screens]


@router.get("/trials")
async def list_trials(): raise NotImplementedError


@router.get("/trials/{nct}")
async def get_trial(nct: str): raise NotImplementedError
