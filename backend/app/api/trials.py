"""Trials from ClinicalTrials.gov (through Zetaris) and their Criteria."""
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException

from app import record, trials
from app.api.deps import get_ctx
from app.api.schemas import (ClosedTrialListOut, ClosedTrialOut, ContactOut, OutcomesOut, PublicationOut, TrialDetailOut,
                             TrialSiteOut)
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


@router.get("/trials/{nct}", response_model=TrialDetailOut)
async def get_trial(nct: str, ctx: Ctx = Depends(get_ctx)):
    """The Trial, who to contact about it (#27) and its Outcomes (#25)."""
    nct_id = trials.NctId(nct)
    t, c, o = await trials.trial(ctx, nct_id), await trials.contacts(ctx, nct_id), await trials.outcomes(ctx, nct_id)
    if t is None or c is None or o is None:
        raise HTTPException(404, f"no Trial {nct}")
    return TrialDetailOut(
        nct_id=t.nct_id, title=t.title, status=t.status, page_url=c.page_url, sponsor=c.sponsor,
        responsible_party=_contact_out(c.responsible_party) if c.responsible_party else None,
        central_contacts=[_contact_out(x) for x in c.central], overall_officials=[_contact_out(x) for x in c.officials],
        sites=[TrialSiteOut(facility=s.facility, city=s.city, status=s.status,
                            contacts=[_contact_out(x) for x in s.contacts]) for s in await trials.sites(ctx, nct_id)],
        outcomes=OutcomesOut(**{**asdict(o), "publications": [PublicationOut(**asdict(p), url=p.url)
                                                             for p in o.publications]}))


def _contact_out(c: trials.Contact) -> ContactOut:
    return ContactOut(**asdict(c))
