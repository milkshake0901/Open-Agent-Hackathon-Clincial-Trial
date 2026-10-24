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

    Dates are parsed by `observed_on` below, which is where an Intake questionnaire's approximate dates are
    accepted as best estimates (#8); every other check applies to questionnaire Documents unchanged.

    Implemented so far: MISSING_DATE, BAD_PAGE, QUOTE_NOT_ON_PAGE, UNIT_OUT_OF_RANGE (#7, #8) and
    DUPLICATE_OF_ACCEPTED (#9, see duplicate_of_accepted). CONTRADICTS_ACCEPTED and IMPOSSIBLE_SEQUENCE are #13.
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
        if current is not None and duplicate_of_accepted(d, doc, current):
            add(FindingKind.DUPLICATE_OF_ACCEPTED, i, f"fact {i + 1} ({d.subject}): already in the record")
    return tuple(findings)


def duplicate_of_accepted(draft: DraftFact, doc: Document, current: ProfileVersion) -> bool:
    """The draft says nothing the accepted record does not already say: same subject, value and unit, and
    - from a clinical Document: the same observed-on date as any accepted Fact (re-reading an old report);
    - from an Intake questionnaire: the subject's current value, in the same words (quote). A resubmission repeats
      unchanged answers on a new date, which is no new observation; but an answer changed back to an earlier value
      is a correction, and an answer reworded more exactly (a Respondent question answered) is new evidence."""
    def same(f: Fact) -> bool:
        return same_subject(f, draft) and f.value == draft.value and (f.unit or None) == (draft.unit or None)
    if doc.is_questionnaire:
        now = next((f for s, f in current.current().items() if _norm_subject(s) == _norm_subject(draft.subject)), None)
        return now is not None and same(now) and now.quote == draft.quote
    return any(same(f) and f.observed_on == draft.observed_on for f in current.facts)


_FULL_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_APPROXIMATE = re.compile(r"^(\d{4})(?:-(\d{2}))?$")


def observed_on(raw: str | None, doc: Document) -> date | None:
    """The observed-on date the Critic accepts for a drafted date string; None is a MISSING_DATE finding.

    A full ISO date is always accepted. An approximate one ("2025-03", "2025") counts as missing on a clinical
    Document, but on an Intake questionnaire it is accepted as a best estimate (ADR 0003): the middle of the
    month or year, never later than the submission. No precision is stored; the Fact's quote keeps the
    Respondent's own words ("around March 2025") for the Matcher to judge."""
    raw = (raw or "").strip()
    if m := _FULL_DATE.match(raw):
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    if not doc.is_questionnaire or not (m := _APPROXIMATE.match(raw)):
        return None
    year, month = int(m.group(1)), m.group(2)
    if month is not None and not 1 <= int(month) <= 12:
        return None
    estimate = date(year, int(month), 15) if month else date(year, 7, 1)
    return min(estimate, doc.uploaded_at)


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def quote_on_page(quote: str, page_text: str) -> bool:
    """Whitespace/case-insensitive containment; tables flattened. Guards against hallucinated citations."""
    q = _squash(quote)
    return bool(q) and q in _squash(page_text)


def same_subject(a: Fact | DraftFact, b: Fact | DraftFact) -> bool:
    """Normalised subject equality (lowercase, collapsed whitespace, punctuation stripped).
    # TODO (#13): units in subjects and a small synonym table."""
    return _norm_subject(a.subject) == _norm_subject(b.subject)


def _norm_subject(subject: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", subject.lower()).split())


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
