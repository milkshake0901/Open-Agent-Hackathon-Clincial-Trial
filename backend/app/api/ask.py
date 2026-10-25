"""Ask one question of a patient's parsed letter. The answer comes back with the box it was read from."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from app import record
from app.api.deps import get_ctx
from app.api.schemas import AskIn, AskOut, GroundedCitationOut
from app.ctx import Ctx
from app.llm import LlmUnavailable

router = APIRouter(tags=["ask"])


@router.post("/patients/{pid}/ask", response_model=AskOut)
async def ask_patient(pid: str, body: AskIn, ctx: Ctx = Depends(get_ctx)):
    question = " ".join(body.question.split())
    if not question:
        raise HTTPException(422, "the question is empty")
    if len(question) > 500:
        raise HTTPException(422, "the question is longer than 500 characters")
    try:
        answer = await record.ask(ctx, record.PatientId(pid), question)
    except LlmUnavailable as e:
        raise HTTPException(503, str(e)) from e
    return AskOut(
        answer=answer.answer, reasoning=answer.reasoning, as_of=answer.as_of,
        patient_label=answer.patient_label, document_hash=answer.document_hash,
        filename=answer.filename, page_count=answer.page_count,
        citations=[GroundedCitationOut(
            span_id=c.span_id, document_hash=c.document_hash, filename=c.filename, page=c.page,
            quote=c.quote, x0=c.x0, y0=c.y0, x1=c.x1, y1=c.y1,
        ) for c in answer.citations],
    )


@router.get("/documents/{document_hash}/pages/{number}/image")
async def page_image(document_hash: str, number: int, ctx: Ctx = Depends(get_ctx)):
    """The stored PDF page. Boxes from a citation are fractions of this image."""
    doc = await record.document(ctx, record.DocumentHash(document_hash))
    if number < 1 or number > len(doc.pages):
        raise HTTPException(404, f"page {number}")
    png = record.page_png(ctx.settings.raw_documents_dir, doc.hash, number)
    return Response(content=png, media_type="image/png")
