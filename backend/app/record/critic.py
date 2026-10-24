"""app/record/critic.py — Consistency critic. PURE: no I/O, no LLM.

The critic is deterministic on purpose: the rules that make a Fact acceptable are the
record module's core knowledge, and they must be the same on day 1 and day 4.
If a plausibility check needs a model later, it is added as one more FindingKind
produced by a function in this file that takes a Completion, not by a second critic.
"""
from __future__ import annotations

import re
from datetime import date

from app.record.types import Document, DraftFact, Fact, Finding, FindingKind, ProfileVersion


def review(drafts: tuple[DraftFact, ...], doc: Document, current: ProfileVersion | None) -> tuple[Finding, ...]:
    """All findings for a draft set. Order: per draft, retryable checks then conflict checks.

    # TODO pseudocode
    #   for i, d in enumerate(drafts):
    #       if d.observed_on is None:                     yield MISSING_DATE (retryable)
    #       if not 1 <= d.page <= len(doc.pages):         yield BAD_PAGE (retryable)
    #       elif not quote_on_page(d.quote, doc.pages[d.page-1]):  yield QUOTE_NOT_ON_PAGE (retryable)
    #       if d.unit and not plausible_range(d.subject, d.value, d.unit):  yield UNIT_OUT_OF_RANGE (retryable)
    #       if current:
    #           same = [f for f in current.facts if same_subject(f, d) and f.observed_on == d.observed_on]
    #           if any(f.value == d.value for f in same):   yield DUPLICATE_OF_ACCEPTED (retryable: drop it)
    #           elif same:                                  yield CONTRADICTS_ACCEPTED (conflict)
    #           if impossible_sequence(d, current.facts):   yield IMPOSSIBLE_SEQUENCE (conflict)
    #   also within-draft contradictions (two drafts, same subject+date, different value) -> conflict with accepted=None

    Implemented so far (#7): MISSING_DATE, BAD_PAGE, QUOTE_NOT_ON_PAGE, UNIT_OUT_OF_RANGE. The checks against
    `current` (DUPLICATE_OF_ACCEPTED #9, CONTRADICTS_ACCEPTED and IMPOSSIBLE_SEQUENCE #13) are still to come.
    """
    findings: list[Finding] = []

    def add(kind: FindingKind, i: int, message: str) -> None:
        findings.append(Finding(kind=kind, draft_index=i, message=message, severity=severity_of(kind)))

    for i, d in enumerate(drafts):
        if d.observed_on is None:
            add(FindingKind.MISSING_DATE, i, f"fact {i + 1} ({d.subject}): no observed-on date")
        if not 1 <= d.page <= len(doc.pages):
            add(FindingKind.BAD_PAGE, i, f"fact {i + 1} ({d.subject}): page {d.page} is not in the document")
        elif not quote_on_page(d.quote, doc.pages[d.page - 1].text):
            add(FindingKind.QUOTE_NOT_ON_PAGE, i, f"fact {i + 1} ({d.subject}): quote not found on page {d.page}")
        if d.unit and not plausible_range(d.subject, d.value, d.unit):
            add(FindingKind.UNIT_OUT_OF_RANGE, i, f"fact {i + 1} ({d.subject}): {d.value} {d.unit} is implausible")
    return tuple(findings)


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def quote_on_page(quote: str, page_text: str) -> bool:
    """Whitespace/case-insensitive containment; tables flattened. Guards against hallucinated citations."""
    q = _squash(quote)
    return bool(q) and q in _squash(page_text)


def same_subject(a: Fact | DraftFact, b: Fact | DraftFact) -> bool:
    """Normalised subject equality (lowercase, strip units/punctuation, small synonym table)."""
    raise NotImplementedError


_RANGES: dict[tuple[str, str], tuple[float, float]] = {
    ("haemoglobin", "g/l"): (30, 250),
    ("haemoglobin", "g/dl"): (3, 25),
    ("creatinine", "umol/l"): (10, 2000),
    ("platelets", "x10^9/l"): (1, 2000),
    ("ecog", "score"): (0, 5),
}


def plausible_range(subject: str, value: str, unit: str) -> bool:
    """Tiny table for common labs (Hb, creatinine, platelets, ECOG 0-5). Unknown subject → True."""
    bounds = _RANGES.get((subject.strip().lower(), unit.strip().lower()))
    if bounds is None:
        return True
    try:
        return bounds[0] <= float(value) <= bounds[1]
    except ValueError:
        return False


def impossible_sequence(draft: DraftFact, accepted: tuple[Fact, ...]) -> bool:
    """# TODO: age decreasing over time; date of death before any later-dated fact; stage regression without treatment."""
    raise NotImplementedError


_CONFLICTS = {FindingKind.CONTRADICTS_ACCEPTED, FindingKind.IMPOSSIBLE_SEQUENCE}


def severity_of(kind: FindingKind) -> str:
    """The single mapping kind → 'retryable' | 'conflict'. Finding.severity is derived from this, never set by hand."""
    return "conflict" if kind in _CONFLICTS else "retryable"
