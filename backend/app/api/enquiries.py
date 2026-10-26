"""Enquiries: an email body the Respondent edits, copies and sends themselves. Nothing is stored or sent here."""
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException

from app import enquiry, llm, record, trials
from app.api.deps import get_ctx, patient_version
from app.api.schemas import ClinicalDetailOut, EnquiryDetailsOut, EnquiryIn, EnquiryOut, RecipientOut
from app.ctx import Ctx

router = APIRouter(tags=["enquiries"])

_PATH = "/patients/{pid}/versions/{vid}/trials/{nct}/enquiry"


@router.get(_PATH, response_model=EnquiryDetailsOut)
async def enquiry_details(pid: str, vid: str, nct: str, ctx: Ctx = Depends(get_ctx)):
    """The clinical details an Enquiry may include, all ticked, for the Respondent to confirm first: no model call.
    404: unknown Trial."""
    await patient_version(ctx, pid, vid)
    try:
        offered = await enquiry.details(ctx, trials.NctId(nct), record.ProfileVersionId(vid))
    except LookupError as err:
        raise HTTPException(404, str(err))
    return EnquiryDetailsOut(nct_id=nct, details=[ClinicalDetailOut(**asdict(d), included=True) for d in offered])


@router.post(_PATH, response_model=EnquiryOut)
async def draft_enquiry(pid: str, vid: str, nct: str, body: EnquiryIn, ctx: Ctx = Depends(get_ctx)):
    """Drafts with only the confirmed details. 404: unknown Trial; 503: model unavailable."""
    await patient_version(ctx, pid, vid)
    try:
        e = await enquiry.draft(ctx, trials.NctId(nct), record.ProfileVersionId(vid), include=frozenset(body.include))
    except LookupError as err:
        raise HTTPException(404, str(err))
    except llm.LlmUnavailable as err:
        raise HTTPException(503, str(err))
    return EnquiryOut(nct_id=e.nct_id, template=e.template, subject=e.subject, body=e.body, sponsor=e.sponsor,
                      recipient=RecipientOut(**asdict(e.recipient)) if e.recipient else None,
                      details=[ClinicalDetailOut(**asdict(d), included=kept) for d, kept in e.details])
