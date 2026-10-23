"""Upload a Document: register it now, run ingest then Re-scan in the background (one correlation id)."""
from fastapi import APIRouter, UploadFile

router = APIRouter(tags=["documents"])


@router.post("/patients/{pid}/documents", status_code=202)
async def upload(pid: str, file: UploadFile):
    """record.register_document → 202 {document_hash, run_id, deduplicated};
    background: record.ingest → on Committed, matching.rescan with the same correlation id."""
    raise NotImplementedError
