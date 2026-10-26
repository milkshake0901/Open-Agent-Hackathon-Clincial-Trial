"""A stored Document's page images and Regions, which a Citation's Region box points into."""
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from app import record
from app.api.deps import get_ctx
from app.api.schemas import DocumentRegionsOut, RegionOut
from app.ctx import Ctx

router = APIRouter(tags=["documents"])


@router.get("/documents/{document_hash}/pages/{number}/image")
async def page_image(document_hash: str, number: int, ctx: Ctx = Depends(get_ctx)):
    """The stored PDF page. Boxes from a citation are fractions of this image."""
    doc = await record.document(ctx, record.DocumentHash(document_hash))
    if number < 1 or number > len(doc.pages):
        raise HTTPException(404, f"page {number}")
    png = record.page_png(ctx.settings.raw_documents_dir, doc.hash, number)
    return Response(content=png, media_type="image/png")


@router.get("/documents/{document_hash}/regions", response_model=DocumentRegionsOut)
async def document_regions(document_hash: str, ctx: Ctx = Depends(get_ctx)):
    """The de-identified Regions read from a stored Document, in reading order, with their boxes."""
    try:
        doc = await record.document_regions(ctx, record.DocumentHash(document_hash))
    except record.NotFound as e:
        raise HTTPException(404, str(e)) from e
    return DocumentRegionsOut(document_hash=doc.document_hash, filename=doc.filename, page_count=doc.page_count,
                              regions=[RegionOut(**asdict(r)) for r in doc.regions])
