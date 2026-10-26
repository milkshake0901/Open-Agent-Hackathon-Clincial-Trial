"""app/extraction — scanned Documents to page text via Nemotron Parse.

Nightshift has no vision lane, so scans go to NVIDIA's parse model through LangChain.
The API key comes from Doppler (`NVIDIA_PARSE_API_KEY`), never from source.
It is not the Nightshift NVIDIA key.
"""
from app.extraction.pages import render_page
from app.extraction.parse import ExtractedBlock, ExtractedDocument, ExtractedPage, extract_pdf

__all__ = ["ExtractedBlock", "ExtractedDocument", "ExtractedPage", "extract_pdf", "render_page"]
