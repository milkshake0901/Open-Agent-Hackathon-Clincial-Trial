"""Patients, their Documents, Profile versions and diffs."""
from fastapi import APIRouter, Depends, HTTPException, Query

from app import record
from app.api.deps import get_ctx
from app.api.verdicts import verdicts_changed
from app.api.schemas import (
    FactOut, PatientCreated, PatientIn, SearchPreferencesIn, SearchPreferencesOut, VersionDiffOut, VersionOut,
)
from app.ctx import Ctx

router = APIRouter(tags=["patients"])


@router.post("/patients", status_code=201, response_model=PatientCreated)
async def create_patient(body: PatientIn, ctx: Ctx = Depends(get_ctx)):
    return PatientCreated(patient_id=await record.create_patient(ctx, body.label))


@router.put("/patients/{pid}/search-preferences", response_model=SearchPreferencesOut)
async def set_search_preferences(pid: str, body: SearchPreferencesIn, ctx: Ctx = Depends(get_ctx)):
    """record.set_search_preferences. 422: a preference that does not fit its question; 404: unknown patient."""
    try:
        p = await record.set_search_preferences(ctx, record.PatientId(pid), body.model_dump(exclude_none=True))
    except record.InvalidAnswers as e:
        raise HTTPException(422, str(e))
    except record.NotFound as e:
        raise HTTPException(404, str(e))
    return SearchPreferencesOut(postcode_set=p.postcode is not None, location_known=p.location is not None,
                                max_travel_km=p.max_travel_km, contact_set=p.contact is not None)


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


def _fact_out(f: record.Fact) -> FactOut:
    return FactOut(id=f.id, resource=f.resource, subject=f.subject, value=f.value, unit=f.unit,
                   observed_on=f.observed_on, citation={"document_hash": f.document_hash, "page": f.page,
                                                        "quote": f.quote, "label": _citation_label(f)})


@router.get("/patients/{pid}/versions/{vid}", response_model=VersionOut)
async def get_version(pid: str, vid: str, ctx: Ctx = Depends(get_ctx)):
    try:
        v = await record.profile_version(ctx, record.ProfileVersionId(vid))
    except record.NotFound as e:
        raise HTTPException(404, str(e))
    if v.patient_id != pid:
        raise HTTPException(404, f"profile version {vid}")
    return VersionOut(id=v.id, number=v.number, document_hash=v.document_hash,
                      facts=[_fact_out(f) for f in v.facts], current={s: f.id for s, f in v.current().items()})


@router.get("/patients/{pid}/versions/{vid}/diff", response_model=VersionDiffOut)
async def version_diff(pid: str, vid: str, from_: str = Query(alias="from"), ctx: Ctx = Depends(get_ctx)):
    """Facts added and subjects changed between two versions (record.diff), and the Verdicts that moved
    (matching.change_between for each Trial judged at the later version)."""
    try:
        d = await record.diff(ctx, record.ProfileVersionId(from_), record.ProfileVersionId(vid))
        v = await record.profile_version(ctx, d.to_version)
    except record.NotFound as e:
        raise HTTPException(404, str(e))
    if v.patient_id != pid:
        raise HTTPException(404, f"profile version {vid}")
    return VersionDiffOut(from_version=d.from_version, to_version=d.to_version,
                          facts_added=[_fact_out(f) for f in d.facts_added],
                          subjects_changed=[{"subject": s, "before": b and _fact_out(b), "after": _fact_out(a)}
                                            for s, b, a in d.subjects_changed],
                          verdicts_changed=await verdicts_changed(ctx, d.from_version, d.to_version))
