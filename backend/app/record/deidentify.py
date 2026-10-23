"""app/record/deidentify.py — removes names, addresses, record numbers and clinician names from
page text BEFORE any model sees it (GLOSSARY: De-identification). Runs inside register_document,
so every Page stored and every Citation shown is already de-identified."""
from __future__ import annotations

from app.record.types import Page


def deidentify(pages: tuple[Page, ...], *, known_names: tuple[str, ...] = ()) -> tuple[Page, ...]:
    """# TODO: deterministic rules first (MRN/Medicare patterns, phone, email, street addresses,
    'Dr <Name>', known_names supplied at patient creation), replaced with stable placeholders
    like [PATIENT], [CLINICIAN-1]. Dates are kept: observed-on dates are clinical data."""
    raise NotImplementedError
