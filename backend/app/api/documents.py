"""Add a Document: register it now, run ingest then Re-scan in the background (one correlation id). A questionnaire
submission follows the same path (start_ingest)."""
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile

from app import matching, record, trace
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
    background: record.ingest → on Committed, matching.rescan with the same correlation id.
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
    return UploadAccepted(document_hash=registered.document.hash, run_id=await start_ingest(ctx, background, registered),
                          deduplicated=registered.deduplicated)


async def start_ingest(ctx: Ctx, background: BackgroundTasks, registered: record.Registered) -> trace.RunId:
    """The run that follows a registered Document: an earlier run for it unless that one was rejected, else a new
    run opened now, whose ingest (then Re-scan on Committed, same correlation id) runs in the background."""
    doc = registered.document
    if registered.deduplicated:
        earlier = await trace.latest_for_document(ctx.ui_reader, doc.hash)
        if earlier is not None and (await trace.project_ingest(ctx.ui_reader, earlier)).phase != "rejected":
            return earlier
    run_id = trace.new_id()
    await trace.open(ctx.writer, run_id, "ingest", patient_id=doc.patient_id, document_hash=doc.hash)
    background.add_task(_ingest, ctx, doc.hash, run_id)
    return run_id


async def _ingest(ctx: Ctx, h: record.DocumentHash, run_id: trace.RunId) -> None:
    try:
        outcome = await record.ingest(ctx, h, run_id=run_id)
    except Exception:   # the run must still end, or the UI would wait on it for ever
        log.exception("ingest of %s failed", h)
        await trace.append(ctx.writer, run_id, RunRejected(actor="record", reason="the Document could not be checked"))
        raise
    if isinstance(outcome, record.Committed):
        await matching.rescan(ctx, outcome.version.id, correlation_id=run_id)
