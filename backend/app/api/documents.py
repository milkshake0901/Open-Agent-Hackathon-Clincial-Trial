"""Add a Document: register it now, run ingest then Re-scan in the background (one correlation id). A questionnaire
submission follows the same path (start_ingest)."""
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile

from app import matching, record, trace
from app.api.deps import get_ctx
from app.api.schemas import DocumentAccepted, SavedLetterOut
from app.ctx import Ctx
from app.trace.events import RunRejected

router = APIRouter(tags=["documents"])
log = logging.getLogger(__name__)


@router.get("/saved-referral", response_model=SavedLetterOut)
async def saved_referral(ctx: Ctx = Depends(get_ctx)):
    """The referral already read into Regions, so a demo can open it without sending the PDF to NVIDIA again."""
    saved = await record.saved_letter(ctx)
    if saved is None:
        raise HTTPException(404, "no saved referral")
    return SavedLetterOut(patient_id=saved.patient_id, document_hash=saved.document_hash,
                          filename=saved.filename, version_id=saved.version_id)

MAX_DOCUMENT_BYTES = 20 * 1024 * 1024


@router.post("/patients/{pid}/documents", status_code=202, response_model=DocumentAccepted)
async def add_document(pid: str, file: UploadFile, background: BackgroundTasks, ctx: Ctx = Depends(get_ctx)):
    """202 {document_hash, run_id, deduplicated} as soon as the file is a PDF. The read into Regions, then
    record.ingest, run after the response; on Committed, matching.rescan with the same correlation id.
    Several files at once are several requests; the UI follows their runs together. Adding the same bytes again
    answers with the run that already handled them, unless that run was rejected, in which case it runs again."""
    content = await file.read(MAX_DOCUMENT_BYTES + 1)
    if len(content) > MAX_DOCUMENT_BYTES:
        raise HTTPException(413, "the file is larger than 20 MB")
    try:
        accepted = await record.accept_upload(ctx, record.PatientId(pid), content)
    except record.UnreadableDocument as e:
        raise HTTPException(422, str(e))
    if accepted.existing is not None:
        registered = record.Registered(accepted.existing, deduplicated=True)
        return DocumentAccepted(document_hash=accepted.document_hash,
                                run_id=await start_ingest(ctx, background, registered), deduplicated=True)
    # The PDF is read after this response, so the page can move on and offer the details when they are ready.
    run_id = trace.new_id()
    await trace.open(ctx.writer, run_id, "ingest", patient_id=pid, document_hash=accepted.document_hash)
    background.add_task(_read_and_ingest, ctx, record.PatientId(pid), file.filename or "document.pdf", content, run_id)
    return DocumentAccepted(document_hash=accepted.document_hash, run_id=run_id, deduplicated=False)


async def start_ingest(ctx: Ctx, background: BackgroundTasks, registered: record.Registered, *,
                       otherwise: record.ProfileVersionId | None = None) -> trace.RunId:
    """The run that follows a registered Document: an earlier run for it unless that one was rejected, else a new
    run opened now, whose ingest (then Re-scan on Committed, same correlation id) runs in the background. `otherwise`:
    the version to Re-scan instead when this ingest does not commit (a Letter review's letter, under its corrections)."""
    doc = registered.document
    if registered.deduplicated:
        earlier = await trace.latest_for_document(ctx.ui_reader, doc.hash)
        if earlier is not None and (await trace.project_ingest(ctx.ui_reader, earlier)).phase != "rejected":
            return earlier
    run_id = trace.new_id()
    await trace.open(ctx.writer, run_id, "ingest", patient_id=doc.patient_id, document_hash=doc.hash)
    background.add_task(_ingest, ctx, doc.hash, run_id, otherwise)
    return run_id


async def _read_and_ingest(ctx: Ctx, patient_id: record.PatientId, filename: str, content: bytes,
                         run_id: trace.RunId) -> None:
    """Read the PDF into Regions, then draft its Facts. Both run after the upload has answered, so a slow read
    does not hold the page. An unreadable PDF rejects the run and stores nothing."""
    try:
        registered = await record.register_document(ctx, patient_id, filename, content)
    except record.UnreadableDocument as e:
        await trace.append(ctx.writer, run_id, RunRejected(actor="record", reason=str(e)))
        return
    except Exception:
        log.exception("reading %s failed", filename)
        await trace.append(ctx.writer, run_id, RunRejected(actor="record", reason="the Document could not be read"))
        return
    await _ingest(ctx, registered.document.hash, run_id)


async def _ingest(ctx: Ctx, h: record.DocumentHash, run_id: trace.RunId,
                  otherwise: record.ProfileVersionId | None = None) -> None:
    try:
        outcome = await record.ingest(ctx, h, run_id=run_id)
    except Exception:   # the run must still end, or the UI would wait on it for ever
        log.exception("ingest of %s failed", h)
        await trace.append(ctx.writer, run_id, RunRejected(actor="record", reason="the Document could not be checked"))
        if otherwise is not None:
            await matching.rescan(ctx, otherwise, correlation_id=run_id)
        raise
    if isinstance(outcome, record.Committed):
        await matching.rescan(ctx, outcome.version.id, correlation_id=run_id)
    elif otherwise is not None:
        await matching.rescan(ctx, otherwise, correlation_id=run_id)
