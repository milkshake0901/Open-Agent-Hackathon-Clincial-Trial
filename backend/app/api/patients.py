"""Patients, their Documents, Profile versions and diffs."""
from fastapi import APIRouter

router = APIRouter(tags=["patients"])


@router.post("/patients", status_code=201)
async def create_patient(body: dict): raise NotImplementedError


@router.get("/patients/{pid}/documents")
async def list_documents(pid: str): raise NotImplementedError


@router.get("/patients/{pid}/documents/{doc_hash}/pages/{n}")
async def document_page(pid: str, doc_hash: str, n: int):
    """De-identified page text; the citation viewer opens this."""
    raise NotImplementedError


@router.get("/patients/{pid}/versions")
async def list_versions(pid: str): raise NotImplementedError


@router.get("/patients/{pid}/versions/{vid}")
async def get_version(pid: str, vid: str): raise NotImplementedError


@router.get("/patients/{pid}/versions/{vid}/diff")
async def version_diff(pid: str, vid: str, from_: str):
    """Facts added, subjects changed and Verdicts changed between two versions: the demo moment."""
    raise NotImplementedError
