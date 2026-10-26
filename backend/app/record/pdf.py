"""app/record/pdf.py — why an uploaded file cannot become a Document. Every PDF is read through the Parser on Ctx
(Nemotron Parse) into pages of Regions; see app/record/referral.py."""
from __future__ import annotations


class UnreadableDocument(Exception):
    """Empty, not a PDF, a PDF that cannot be rendered, or one in which the parse finds no readable text."""
