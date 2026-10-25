"""Enquiries: an email body the Respondent edits, copies and sends themselves. Nothing is stored or sent here."""
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException

from app import enquiry, llm, record, trials
from app.api.deps import get_ctx, patient_version
from app.api.schemas import ClinicalDetailOut, EnquiryIn, EnquiryOut, RecipientOut
from app.ctx import Ctx

router = APIRouter(tags=["enquiries"])


@router.post("/patients/{pid}/versions/{vid}/trials/{nct}/enquiry", response_model=EnquiryOut)
async def draft_enquiry(pid: str, vid: str, nct: str, body: EnquiryIn, ctx: Ctx = Depends(get_ctx)):
    """404: unknown Trial, or an Open trial with no Verdict at this version (a Closed trial needs none); 503: model
    unavailable."""
    await patient_version(ctx, pid, vid)
    try:
        e = await enquiry.draft(ctx, trials.NctId(nct), record.ProfileVersionId(vid),
                                include=None if body.include is None else frozenset(body.include))
    except LookupError as err:
        raise HTTPException(404, str(err))
    except llm.LlmUnavailable as err:
        raise HTTPException(503, str(err))
    return EnquiryOut(nct_id=e.nct_id, template=e.template, subject=e.subject, body=e.body, sponsor=e.sponsor,
                      recipient=RecipientOut(**asdict(e.recipient)) if e.recipient else None,
                      details=[ClinicalDetailOut(**asdict(d), included=kept) for d, kept in e.details])
