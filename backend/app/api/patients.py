"""Patients, their Documents, Profile versions and diffs."""
from fastapi import APIRouter, Depends, HTTPException

from app import record
from app.api.deps import get_ctx
from app.api.schemas import PatientCreated, PatientIn, VersionOut
from app.ctx import Ctx

router = APIRouter(tags=["patients"])


@router.post("/patients", status_code=201, response_model=PatientCreated)
async def create_patient(body: PatientIn, ctx: Ctx = Depends(get_ctx)):
    return PatientCreated(patient_id=await record.create_patient(ctx, body.label))


@router.get("/patients/{pid}/documents")
async def list_documents(pid: str): raise NotImplementedError


@router.get("/patients/{pid}/documents/{doc_hash}/pages/{n}")
async def document_page(pid: str, doc_hash: str, n: int):
    """De-identified page text; the citation viewer opens this."""
    raise NotImplementedError


@router.get("/patients/{pid}/versions")
async def list_versions(pid: str): raise NotImplementedError


def _citation_label(f: record.Fact) -> str:
    return f"Patient-reported, intake questionnaire, {f.question}" if f.question else f"page {f.page}"


@router.get("/patients/{pid}/versions/{vid}", response_model=VersionOut)
async def get_version(pid: str, vid: str, ctx: Ctx = Depends(get_ctx)):
    try:
        v = await record.profile_version(ctx, record.ProfileVersionId(vid))
    except record.NotFound as e:
        raise HTTPException(404, str(e))
    if v.patient_id != pid:
        raise HTTPException(404, f"profile version {vid}")
    return VersionOut(id=v.id, number=v.number, document_hash=v.document_hash, facts=[
        {"id": f.id, "resource": f.resource, "subject": f.subject, "value": f.value, "unit": f.unit,
         "observed_on": f.observed_on, "citation": {"document_hash": f.document_hash, "page": f.page,
                                                    "quote": f.quote, "label": _citation_label(f)}}
        for f in v.facts], current={s: f.id for s, f in v.current().items()})


@router.get("/patients/{pid}/versions/{vid}/diff")
async def version_diff(pid: str, vid: str, from_: str):
    """Facts added, subjects changed and Verdicts changed between two versions: the demo moment."""
    raise NotImplementedError
