"""Measure a washout from the letter's dates to today.

An exclusion that forbids a treatment within N days, weeks, or months is a clock question. The model
reads the words. This module does the subtraction, and the answer has to follow it.
"""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date

from app.record import LetterSpan
from app.trials import Criterion

# A name in a criterion, and the words a letter uses for the same treatment. Androgen suppression is
# left out: the trials that name it say it is permitted, so it is not a washout.
_ALIASES: dict[str, tuple[str, ...]] = {
    "anticancer": ("anticancer", "chemotherapy", "chemo", "immunotherapy", "pembrolizumab", "taxotere",
                   "docetaxel", "cabazitaxel", "radioligand", "lu-177", "lutetium", "terbium",
                   "enzalutamide", "xtandi", "darolutamide", "apalutamide", "abiraterone", "zytiga", "olaparib"),
    "radioligand": ("radioligand", "lu-177", "lutetium", "terbium", "rlt"),
    "radionuclide": ("radionuclide", "radium"),
    "radiotherapy": ("radiotherapy", "radiation", "tomotherapy", " rt "),
    "chemotherapy": ("chemotherapy", "chemo", "taxotere", "docetaxel", "cabazitaxel", "carboplatin"),
    "immunotherapy": ("immunotherapy", "pembrolizumab"),
    "enzalutamide": ("enzalutamide", "xtandi"),
    "darolutamide": ("darolutamide",),
    "apalutamide": ("apalutamide",),
    "abiraterone": ("abiraterone", "zytiga"),
    "vaccine": ("vaccine",),
    "investigational": ("investigational",),
}

_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3, "apr": 4, "april": 4,
    "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7, "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9, "oct": 10, "october": 10, "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}
_MONTH = r"Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?"
_DMY = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b")
_D_MONTH_Y = re.compile(rf"\b(\d{{1,2}})\s+({_MONTH})\s+(\d{{4}})\b", re.I)
_MONTH_Y = re.compile(rf"\b({_MONTH})\s+(\d{{4}})\b", re.I)
_WINDOW = re.compile(
    r"(?:within|washout of|minimum washout of)\s+(\d+)\s+(day|week|month)s?",
    re.I,
)
_UNIT_DAYS = {"day": 1, "week": 7, "month": 30}


@dataclass(frozen=True)
class Washout:
    """One timed exclusion measured against today. cleared means the latest letter date is outside the window."""
    criterion_id: str
    clause: str
    window_days: int
    last_on: date
    days_before: int
    span_id: str
    cleared: bool


def window_days(text: str) -> int | None:
    """The longest 'within N days/weeks/months' in the text, in days. None when the line has no such window."""
    found = [int(n) * _UNIT_DAYS[unit.lower()] for n, unit in _WINDOW.findall(text)]
    return max(found) if found else None


def dates_in(text: str) -> tuple[date, ...]:
    """Dates written as D/M/YY, '3 Feb 2026', or 'September 2025'. A bare month is the last day of that month."""
    found: list[date] = []
    used: list[tuple[int, int]] = []

    def take(start: int, end: int, value: date | None) -> None:
        if value is None or any(start < b and end > a for a, b in used):
            return
        used.append((start, end))
        found.append(value)

    for match in _DMY.finditer(text):
        take(match.start(), match.end(), _dmy(int(match.group(1)), int(match.group(2)), int(match.group(3))))
    for match in _D_MONTH_Y.finditer(text):
        month = _MONTHS[match.group(2).casefold()]
        take(match.start(), match.end(), _dmy(int(match.group(1)), month, int(match.group(3))))
    for match in _MONTH_Y.finditer(text):
        month = _MONTHS[match.group(1).casefold()]
        year = int(match.group(2))
        take(match.start(), match.end(), date(year, month, calendar.monthrange(year, month)[1]))
    return tuple(found)


def measure(criteria: tuple[Criterion, ...], spans: tuple[LetterSpan, ...], today: date) -> tuple[Washout, ...]:
    """Each exclusion with a time window, measured from the latest matching date on the letter to today."""
    text_spans = tuple(span for span in spans if span.kind == "Text" and span.text.strip())
    measured: list[Washout] = []
    for criterion in criteria:
        if str(criterion.kind) != "exclusion":
            continue
        window = window_days(criterion.text)
        if window is None:
            continue
        scope = _without_permitted(criterion.text)
        needles = _needles(scope)
        if not needles:
            continue
        latest: tuple[date, LetterSpan] | None = None
        for span in text_spans:
            hay = f" {span.text.casefold()} "
            if not any(needle in hay for needle in needles):
                continue
            for on in dates_in(span.text):
                if latest is None or on > latest[0]:
                    latest = (on, span)
        if latest is None:
            continue
        on, span = latest
        days = (today - on).days
        measured.append(Washout(
            criterion_id=criterion.id, clause=_clause(criterion.text), window_days=window, last_on=on,
            days_before=days, span_id=span.id, cleared=days > window,
        ))
    return tuple(measured)


def clock_text(criteria: tuple[Criterion, ...], spans: tuple[LetterSpan, ...], today: date) -> str:
    """What the model is given. The intervals are already calculated."""
    lines = [f"Clock tool. Today is {today.isoformat()}. These intervals are measured. Do not estimate them.",
             "A washout (within N days, weeks, or months) is not met when the latest date for that treatment is more than N before today."]
    rows = measure(criteria, spans, today)
    if not rows:
        lines.append("No washout on this trial had a dated treatment on the letter.")
    for row in rows:
        state = "the washout has passed" if row.cleared else "this is still inside the window"
        lines.append(
            f"[{row.criterion_id}] window {row.window_days} days. Latest date {row.last_on.isoformat()} "
            f"on [{row.span_id}] is {row.days_before} days before today, so {state}. Clause: {row.clause}")
    return "\n".join(lines)


def _dmy(day: int, month: int, year: int) -> date | None:
    if year < 100:
        year += 2000
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _without_permitted(text: str) -> str:
    parts = re.split(r"(?<=\.)\s+", " ".join(text.split()))
    return " ".join(part for part in parts if "permitted" not in part.casefold())


def _needles(text: str) -> tuple[str, ...]:
    folded = f" {text.casefold()} "
    found: list[str] = []
    for key, names in _ALIASES.items():
        if key in folded:
            found.extend(names)
    return tuple(dict.fromkeys(found))


def _clause(text: str) -> str:
    flat = " ".join(text.split())
    for part in re.split(r"(?<=\.)\s+", flat):
        if _WINDOW.search(part):
            return part.strip()
    return flat
