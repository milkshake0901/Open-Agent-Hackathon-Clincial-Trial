"""Upload a Document: register it now, run ingest then Re-scan in the background (one correlation id)."""
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile

from app import record, trace
from app.api.deps import get_ctx
from app.api.schemas import UploadAccepted
from app.ctx import Ctx
from app.trace.events import RunRejected

router = APIRouter(tags=["documents"])
log = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 20 * 1024 * 1024


@router.post("/patients/{pid}/documents", status_code=202, response_model=UploadAccepted)
async def upload(pid: str, file: UploadFile, background: BackgroundTasks, ctx: Ctx = Depends(get_ctx)):
    """record.register_document → 202 {document_hash, run_id, deduplicated};
    background: record.ingest → on Committed, matching.rescan with the same correlation id (#12).
    Several files at once are several requests; the UI follows their runs together. A re-upload of the same bytes
    answers with the run that already handled them, unless that run was rejected, in which case it runs again."""
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "the file is larger than 20 MB")
    try:
        registered = await record.register_document(ctx, record.PatientId(pid), file.filename or "document.pdf",
                                                    content)
    except record.NotFound as e:
        raise HTTPException(404, str(e))
    except record.UnreadableDocument as e:
        raise HTTPException(422, str(e))
    h = registered.document.hash
    if registered.deduplicated:
        earlier = await trace.latest_for_document(ctx.ui_reader, h)
        if earlier is not None and (await trace.project_ingest(ctx.ui_reader, earlier)).phase != "rejected":
            return UploadAccepted(document_hash=h, run_id=earlier, deduplicated=True)
    run_id = trace.new_id()
    await trace.open(ctx.writer, run_id, "ingest", patient_id=pid, document_hash=h)
    background.add_task(_ingest, ctx, h, run_id)
    return UploadAccepted(document_hash=h, run_id=run_id, deduplicated=registered.deduplicated)


async def _ingest(ctx: Ctx, h: record.DocumentHash, run_id: trace.RunId) -> None:
    try:
        await record.ingest(ctx, h, run_id=run_id)
    except Exception:   # the run must still end, or the UI would wait on it for ever
        log.exception("ingest of %s failed", h)
        await trace.append(ctx.writer, run_id, RunRejected(actor="record", reason="the Document could not be checked"))
        raise
    # TODO(#12): on Committed, matching.rescan(ctx, version, correlation_id=run_id).
