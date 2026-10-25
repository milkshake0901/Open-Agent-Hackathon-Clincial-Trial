"""Render one PDF page to a PNG the parse model can read. PDFs themselves are refused."""
from __future__ import annotations

import io

import pypdfium2 as pdfium

MAX_SIDE = 1600  # nemotron-parse accepts up to about 1648 x 2048


def render_pages(content: bytes) -> tuple[bytes, ...]:
    """PNG bytes, one per page, longest side at most MAX_SIDE pixels."""
    if not content.startswith(b"%PDF"):
        raise ValueError("the file is not a PDF")
    pdf = pdfium.PdfDocument(content)
    try:
        images: list[bytes] = []
        for page in pdf:
            width, height = page.get_size()
            scale = MAX_SIDE / max(width, height, 1)
            pil = page.render(scale=scale).to_pil()
            buf = io.BytesIO()
            pil.save(buf, format="PNG")
            images.append(buf.getvalue())
        if not images:
            raise ValueError("the PDF has no pages")
        return tuple(images)
    finally:
        pdf.close()


def render_page(content: bytes, number: int) -> bytes:
    """PNG of one page, 1-based. The same pixels the parse boxes were measured against."""
    pages = render_pages(content)
    if number < 1 or number > len(pages):
        raise ValueError(f"page {number} is outside this PDF ({len(pages)} pages)")
    return pages[number - 1]
