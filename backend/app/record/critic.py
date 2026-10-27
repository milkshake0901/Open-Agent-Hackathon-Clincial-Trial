"""app/record/critic.py — Consistency critic. PURE: no I/O, no LLM.

The critic is deterministic on purpose: the rules that make a Fact acceptable are the
record module's core knowledge, and they must be the same on day 1 and day 4.
If a plausibility check needs a model later, it is added as one more FindingKind
produced by a function in this file that takes a Completion, not by a second critic.
"""
from __future__ import annotations

import re
from datetime import date
from difflib import SequenceMatcher

from app.record import dates
from app.record.types import Document, DraftFact, Fact, Finding, FindingKind, ProfileVersion


def review(drafts: tuple[DraftFact, ...], doc: Document, current: ProfileVersion | None) -> tuple[Finding, ...]:
    """All findings for a draft set. Per draft, in order:
      MISSING_DATE        no observed-on date (retryable)
      UNKNOWN_REGION      on a Document read into Regions, the span_id names none it can cite (retryable), else
      QUOTE_NOT_IN_REGION the quote is not inside that Region (retryable); on a Document without Regions:
      BAD_PAGE            the page is not in the Document (retryable), else
      QUOTE_NOT_ON_PAGE   the quote is not on that page (retryable)
      NUMBER_NOT_IN_QUOTE on a clinical Document, a number in the value the quote does not have (retryable)
      DATE_AGAINST_ORDER  on a clinical Document, the observed-on date is a date of the quote read against the
                          Document's date order (dates.date_order) (retryable)
      UNIT_OUT_OF_RANGE   an implausible lab value for its unit (retryable)
      DUPLICATE_OF_ACCEPTED  the record already says it (duplicate_of_accepted; the loop drops it), else
      CONTRADICTS_ACCEPTED   it cannot be true alongside an accepted Fact (contradicts_accepted; a conflict)

    Dates are parsed by `observed_on` below, which is where an Intake questionnaire's approximate dates are
    accepted as best estimates (#8); every other check applies to questionnaire Documents unchanged.
    Not yet checked: IMPOSSIBLE_SEQUENCE (impossible_sequence), and two drafts contradicting each other.
    """
    findings: list[Finding] = []

    def add(kind: FindingKind, i: int, message: str) -> None:
        findings.append(Finding(kind=kind, draft_index=i, message=message, severity=severity_of(kind)))

    order = None if doc.is_questionnaire else dates.date_order(p.text for p in doc.pages)
    for i, d in enumerate(drafts):
        if d.observed_on is None:
            add(FindingKind.MISSING_DATE, i, f"fact {i + 1} ({d.subject}): no observed-on date")
        if doc.regions and not doc.is_questionnaire and (region := doc.region(d.span_id)) is None:
            add(FindingKind.UNKNOWN_REGION, i, f"fact {i + 1} ({d.subject}): span_id {d.span_id!r} is not one of "
                                               "the Regions shown for this page")
        elif doc.regions and not doc.is_questionnaire:
            if not quote_on_page(d.quote, region.text):
                add(FindingKind.QUOTE_NOT_IN_REGION, i, f"fact {i + 1} ({d.subject}): the quote is not inside Region "
                                                        f"{d.span_id}; copy it from that Region's words")
        elif not 1 <= d.page <= len(doc.pages):
            add(FindingKind.BAD_PAGE, i, f"fact {i + 1} ({d.subject}): page {d.page} is not in the document")
        elif not quote_on_page(d.quote, doc.pages[d.page - 1].text):
            add(FindingKind.QUOTE_NOT_ON_PAGE, i, f"fact {i + 1} ({d.subject}): quote not found on page {d.page}")
        if not doc.is_questionnaire and (missing := numbers_not_in_quote(d.value, d.quote)):
            add(FindingKind.NUMBER_NOT_IN_QUOTE, i, f"fact {i + 1} ({d.subject}): the value has "
                                                    f"{', '.join(missing)}, which the quote does not")
        if order and d.observed_on is not None and (read := read_against_order(d.observed_on, d.quote, order)):
            add(FindingKind.DATE_AGAINST_ORDER, i, f"fact {i + 1} ({d.subject}): this document writes dates "
                                                   f"{order.replace('_', ' ')}, so \"{read.text}\" is "
                                                   f"{read.on.isoformat()}, not {d.observed_on.isoformat()}")
        if d.unit and not plausible_range(d):
            add(FindingKind.UNIT_OUT_OF_RANGE, i, f"fact {i + 1} ({d.subject}): {d.value} {d.unit} is implausible")
        if current is not None and duplicate_of_accepted(d, doc, current):
            add(FindingKind.DUPLICATE_OF_ACCEPTED, i, f"fact {i + 1} ({d.subject}): already in the record")
        elif current is not None and d.observed_on is not None and (other := contradicts_accepted(d, doc, current)):
            source = (f"the intake questionnaire ({other.question})" if other.question
                      else f"an earlier document (page {other.page})")
            findings.append(Finding(
                kind=FindingKind.CONTRADICTS_ACCEPTED, draft_index=i, accepted_fact_id=other.id,
                severity=severity_of(FindingKind.CONTRADICTS_ACCEPTED),
                message=f"{d.subject}: page {d.page} says \"{d.quote}\", but {source} says \"{other.quote}\""))
    return tuple(findings)


# A Patient-reported answer about the present and a clinical observation this close to it describe the same time.
PATIENT_REPORTED_WINDOW_DAYS = 90


def contradicts_accepted(draft: DraftFact, doc: Document, current: ProfileVersion) -> Fact | None:
    """The accepted Fact this draft cannot be true alongside (GLOSSARY "Conflict"), or None. Same subject (synonyms
    included: the questionnaire's "daily activity" is the ECOG performance status) with a different value, and
    - between two clinical Documents: the same observed-on date;
    - between a clinical Document and the Patient-reported record: the subject's current Patient-reported Fact,
      observed within PATIENT_REPORTED_WINDOW_DAYS of the draft.
    Two questionnaire answers never conflict: a resubmission is a correction (#9)."""
    key, value = _canonical(draft)
    candidates = [f for f in current.facts if f.question is None]
    if not doc.is_questionnaire:
        latest = None   # the current Patient-reported Fact: the latest submission's, as in current()
        for f in current.facts:
            if f.question is not None and _canonical(f)[0] == key:
                latest = f
        candidates += [latest] if latest else []
    for f in candidates:
        if _canonical(f)[0] != key or _canonical(f)[1] == value:
            continue
        clinical_pair = f.question is None and not doc.is_questionnaire
        days = abs((f.observed_on - draft.observed_on).days)
        if days == 0 or (not clinical_pair and days <= PATIENT_REPORTED_WINDOW_DAYS):
            return f
    return None


# Subjects that name the same thing. Values are compared after _VALUE_SYNONYMS for the canonical subject.
_SUBJECT_SYNONYMS = {
    "daily activity": "ecog performance status",
    "ecog": "ecog performance status",
    "ecog ps": "ecog performance status",
    "performance status": "ecog performance status",
}
# The questionnaire's Q13 options are the ECOG grades in plain words.
_VALUE_SYNONYMS = {
    "ecog performance status": {"fully_active": "0", "light_activity": "1", "self_care": "2",
                                "limited_self_care": "3", "bed_bound": "4"},
}


def subject_key(subject: str) -> str:
    """The one subject normaliser: lowercase, punctuation stripped, whitespace collapsed, synonyms resolved
    ("ECOG PS" and the questionnaire's "daily activity" are both "ecog performance status")."""
    norm = " ".join(re.sub(r"[^\w\s]", " ", subject.lower()).split())
    return _SUBJECT_SYNONYMS.get(norm, norm)


def _canonical(f: Fact | DraftFact) -> tuple[str, str]:
    """(subject, value) with synonyms resolved; unit folded into the value except for unitless scores."""
    subject = subject_key(f.subject)
    value = _squash(f.value)
    if subject == "ecog performance status":
        value = _VALUE_SYNONYMS[subject].get(f.value.strip(), re.sub(r"^(ecog|ps)\s*", "", value))
        return subject, value
    return subject, f"{value} {_squash(f.unit or '')}".strip()


def duplicate_of_accepted(draft: DraftFact, doc: Document, current: ProfileVersion) -> bool:
    """The draft says nothing the accepted record does not already say: same subject, value and unit, and
    - from a clinical Document: the same observed-on date as any accepted Fact (re-reading an old report);
    - from an Intake questionnaire: the subject's current value, in the same words (quote). A resubmission repeats
      unchanged answers on a new date, which is no new observation; but an answer changed back to an earlier value
      is a correction, and an answer reworded more exactly (a Respondent question answered) is new evidence."""
    def same(f: Fact) -> bool:
        return same_subject(f, draft) and f.value == draft.value and (f.unit or None) == (draft.unit or None)
    if doc.is_questionnaire:
        now = next((f for s, f in current.current().items() if subject_key(s) == subject_key(draft.subject)), None)
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


_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def numbers_not_in_quote(value: str, quote: str) -> tuple[str, ...]:
    """The numbers written in a value that the quote does not have, as numbers ("1" is not in "11.2")."""
    have = {float(n) for n in _NUMBER.findall(quote)}
    return tuple(dict.fromkeys(n for n in _NUMBER.findall(value) if float(n) not in have))


def read_against_order(observed_on: date, quote: str, order: dates.DateOrder) -> dates.DateRead | None:
    """The date of the quote that `observed_on` reads in the opposite order to the Document's, when it is not also
    one of the quote's dates read the Document's way."""
    found = dates.dates_in(quote, order)
    if any(r.on == observed_on for r in found):
        return None
    return next((r for r in found if r.other == observed_on), None)


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


# Nemotron Parse writes Markdown, so a letter's "<0.01" can come back as "\<0.01"; a model quoting it writes "<0.01".
_MARKDOWN_ESCAPE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!<>|~])")
# How many letters a quote may differ from its text by: a word the parse misread ("paraaotic") that the model wrote
# as the letter has it ("paraaortic"). Never a digit, and only in a quote long enough to still be that sentence.
QUOTE_TYPOS = 2
_FUZZY_MIN_LEN = 20


def _plain(text: str) -> str:
    return _squash(_MARKDOWN_ESCAPE.sub(r"\1", text))


def quote_on_page(quote: str, page_text: str) -> bool:
    """Whitespace/case-insensitive containment, Markdown escapes ignored; tables flattened. Up to QUOTE_TYPOS
    letters may differ, none of them a digit. Guards against hallucinated citations."""
    q, text = _plain(quote), _plain(page_text)
    return bool(q) and (q in text or _nearly_in(q, text))


def _nearly_in(q: str, text: str) -> bool:
    """`q` is in `text` but for at most QUOTE_TYPOS letters added, dropped or changed, none of them a digit."""
    if len(q) < _FUZZY_MIN_LEN:
        return False
    anchor = SequenceMatcher(None, q, text, autojunk=False).find_longest_match(0, len(q), 0, len(text))
    start = max(0, anchor.b - anchor.a - QUOTE_TYPOS)
    window = text[start:anchor.b - anchor.a + len(q) + QUOTE_TYPOS]
    ops = SequenceMatcher(None, q, window, autojunk=False).get_opcodes()
    while ops and ops[0][0] == "insert":    # the window's own letters before the quote starts
        ops = ops[1:]
    while ops and ops[-1][0] == "insert":   # and after it ends
        ops = ops[:-1]
    edits = [(q[i1:i2], window[j1:j2]) for tag, i1, i2, j1, j2 in ops if tag != "equal"]
    return (sum(max(len(a), len(b)) for a, b in edits) <= QUOTE_TYPOS
            and not any(c.isdigit() for a, b in edits for c in a + b))


def same_subject(a: Fact | DraftFact, b: Fact | DraftFact) -> bool:
    """Subject equality after subject_key (synonyms included)."""
    return subject_key(a.subject) == subject_key(b.subject)


_RANGES: dict[tuple[str, str], tuple[float, float]] = {
    ("haemoglobin", "g/l"): (30, 250),
    ("haemoglobin", "g/dl"): (3, 25),
    ("creatinine", "umol/l"): (10, 2000),
    ("platelets", "x10^9/l"): (1, 2000),
    ("ecog performance status", "score"): (0, 5),
}


def plausible_range(d: DraftFact) -> bool:
    """Tiny table for common labs (Hb, creatinine, platelets, ECOG 0-5), keyed by subject_key. Unknown → True."""
    bounds = _RANGES.get((subject_key(d.subject), (d.unit or "").strip().lower()))
    if bounds is None:
        return True
    try:
        return bounds[0] <= float(d.value) <= bounds[1]
    except ValueError:
        return False


def impossible_sequence(draft: DraftFact, accepted: tuple[Fact, ...]) -> bool:
    """# TODO: age decreasing over time; date of death before any later-dated fact; stage regression without treatment."""
    raise NotImplementedError


_CONFLICTS = {FindingKind.CONTRADICTS_ACCEPTED, FindingKind.IMPOSSIBLE_SEQUENCE}


def severity_of(kind: FindingKind) -> str:
    """The single mapping kind → 'retryable' | 'conflict'. Finding.severity is derived from this, never set by hand."""
    return "conflict" if kind in _CONFLICTS else "retryable"
