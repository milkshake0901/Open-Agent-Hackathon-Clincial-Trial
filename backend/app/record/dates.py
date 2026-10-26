"""app/record/dates.py — dates follow the Document (GLOSSARY "Document date"). PURE: no I/O, no model.

Interface: dating(doc) once per Document, then observed_on(model's date, quote, dating) per drafted Fact. The pieces
(date_order, dates_in, document_date, relative_date) are the rules it is made of.

A Document writes its numeric dates one way: day first ("23/11/23") or month first ("11/23/23"). Its date order is
worked out from any date that reads only one way; with none, its ambiguous dates are flagged, never guessed.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
import calendar
from datetime import date, timedelta
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from app.record.types import Document

DateOrder = Literal["day_first", "month_first"]
DateFlag = Literal["ambiguous_date", "estimated_date", "document_date"]
"""How a drafted Fact's observed-on date was settled, kept on the DraftFact and the Fact:
  ambiguous_date  the date reads two ways and the Document has no date order (flagged for Letter review)
  estimated_date  a best estimate of a relative date, counted back from the Document date (flagged for Letter review)
  document_date   the Fact gave no date of its own, so it is the Document date"""
REVIEW_FLAGS: frozenset[DateFlag] = frozenset({"ambiguous_date", "estimated_date"})
"""The flags Letter review shows first: a Fact with any of them is `flagged`."""

# d/m/y or m/d/y with / . or - between three parts, the year of two or four digits. Two parts (142/86) is no date.
_NUMERIC = re.compile(r"(?<![\d/.\-])(\d{1,2})([/.\-])(\d{1,2})\2(\d{4}|\d{2})(?![\d/\-]|\.\d)")


def date_order(texts: Iterable[str]) -> DateOrder | None:
    """The Document's date order, from its numeric dates that read only one way (a first part over 12 is a day, a
    second part over 12 is a day). None when no date settles it, or when dates settle it both ways."""
    seen: set[DateOrder] = set()
    for text in texts:
        for m in _NUMERIC.finditer(text):
            first, second = int(m.group(1)), int(m.group(3))
            if first > 12 >= second >= 1:
                seen.add("day_first")
            elif second > 12 >= first >= 1:
                seen.add("month_first")
    return seen.pop() if len(seen) == 1 else None


_MONTHS = {name: n for n, names in enumerate(
    (("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"), ("may",), ("jun", "june"),
     ("jul", "july"), ("aug", "august"), ("sep", "sept", "september"), ("oct", "october"), ("nov", "november"),
     ("dec", "december")), 1) for name in names}
_MONTH = r"(" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")\.?"
_DAY_MONTH_YEAR = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+" + _MONTH + r",?\s+(\d{4})\b", re.IGNORECASE)
_MONTH_DAY_YEAR = re.compile(r"\b" + _MONTH + r"\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", re.IGNORECASE)
_ISO = re.compile(r"(?<![\d\-])(\d{4})-(\d{2})-(\d{2})(?![\d\-])")


@dataclass(frozen=True)
class DateRead:
    """One date written in a text, read the way its Document writes dates.
    on: the reading in the Document's date order, or day first when the Document has none.
    other: the reading in the opposite order, when the words allow it and it is a different day.
    ambiguous: the Document has no date order and `other` exists, so the date is flagged, not guessed."""
    text: str
    start: int
    on: date
    other: date | None = None
    ambiguous: bool = False


def _date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _year(raw: str) -> int:
    """A two-digit year is 20yy below 70, else 19yy."""
    y = int(raw)
    return y if len(raw) == 4 else (2000 + y if y < 70 else 1900 + y)


def dates_in(text: str, order: DateOrder | None) -> tuple[DateRead, ...]:
    """Every date written in `text`, in the order written: numeric (d/m/y or m/d/y), written out ("02 October 2026",
    "Oct 3, 2026") or ISO. A date that does not exist ("31/2/23" day first) is not read."""
    found: list[DateRead] = []
    for m in _NUMERIC.finditer(text):
        a, b, year = int(m.group(1)), int(m.group(3)), _year(m.group(4))
        day_first, month_first = _date(year, b, a), _date(year, a, b)
        mine, theirs = (month_first, day_first) if order == "month_first" else (day_first, month_first)
        if mine is None:
            continue
        other = theirs if theirs not in (None, mine) else None
        found.append(DateRead(m.group(0), m.start(), mine, other, ambiguous=order is None and other is not None))
    for pattern, parts in ((_DAY_MONTH_YEAR, (3, 2, 1)), (_MONTH_DAY_YEAR, (3, 1, 2)), (_ISO, (1, 2, 3))):
        for m in pattern.finditer(text):
            y, mo, d = (m.group(i) for i in parts)
            month = int(mo) if mo.isdigit() else _MONTHS[mo.lower().rstrip(".")]
            if (on := _date(int(y), month, int(d))) is not None:
                found.append(DateRead(m.group(0), m.start(), on))
    return tuple(sorted(found, key=lambda r: r.start))


# Labels in front of a Document date, best first: when a test was done, then when a letter was written.
_DATE_LABELS = (
    re.compile(r"\b(?:date of (?:service|examination|exam|study|scan|procedure|collection|test)|"
               r"(?:service|examination|exam|study|scan|procedure|collection|test) date)\b", re.IGNORECASE),
    re.compile(r"\b(?:dictated|date of letter|letter date|clinic date|date seen|seen on|dated|date)\b",
               re.IGNORECASE),
)


def document_date(page_one: Iterable[str], order: DateOrder | None) -> DateRead | None:
    """The Document date (GLOSSARY) from the texts of the first page, read in the Document's date order: the first
    date after a test-date label ("Date of service"), else after a letter-date label ("Dictated:", "Date:"), each on
    the same line; else the first date on the page. None when the first page gives no date. An ambiguous one is
    returned flagged (ambiguous), read day first."""
    lines = [line for text in page_one for line in text.splitlines()]
    for label in _DATE_LABELS:
        for line in lines:
            if (m := label.search(line)) and (after := dates_in(line[m.end():], order)):
                return after[0]
    return next((found[0] for line in lines if (found := dates_in(line, order))), None)


_COUNTS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
           "nine": 9, "ten": 10, "eleven": 11, "twelve": 12}
_AGO = re.compile(r"\b(\d{1,3}|" + "|".join(_COUNTS) + r")\s+(day|week|month|year)s?\s+ago\b", re.IGNORECASE)


def _months_back(on: date, months: int) -> date:
    year, month = divmod(on.year * 12 + on.month - 1 - months, 12)
    return date(year, month + 1, min(on.day, calendar.monthrange(year, month + 1)[1]))


def relative_date(text: str, document_date: date) -> date | None:
    """The best estimate of a relative date in `text` ("4 months ago", "two weeks ago"), counted back from the
    Document date; None when the text has none. A month back from the 31st lands on the shorter month's last day."""
    if (m := _AGO.search(text)) is None:
        return None
    raw, unit = m.group(1).lower(), m.group(2).lower()
    n = int(raw) if raw.isdigit() else _COUNTS[raw]
    if unit in ("day", "week"):
        return document_date - timedelta(days=n * (7 if unit == "week" else 1))
    return _months_back(document_date, n * (12 if unit == "year" else 1))


@dataclass(frozen=True)
class Dating:
    """What a Document says about its dates: its date order, and its Document date (None when its first page has
    none; flagged ambiguous when that date reads two ways)."""
    order: DateOrder | None
    document_date: DateRead | None


def dating(doc: "Document") -> Dating:
    """A Document's date order from the de-identified text of all its pages, and its Document date from its first,
    unless the Respondent corrected it in Letter review (doc.document_date), which is then the Document date."""
    order = date_order(p.text for p in doc.pages)
    if doc.document_date is not None:
        return Dating(order, DateRead(doc.document_date.isoformat(), 0, doc.document_date))
    return Dating(order, document_date([doc.pages[0].text] if doc.pages else [], order))


def redated(on: date | None, flags: tuple[str, ...], quote: str, corrected: date) -> tuple[date | None, tuple[str, ...]]:
    """A drafted Fact's observed-on date and flags once the Respondent corrects its Document's date: a Fact dated by
    the Document date takes the corrected one, a relative date is counted back from it again, and neither is ambiguous
    any more (that came from the Document date). A Fact with a date of its own keeps it."""
    if "document_date" in flags:
        on = corrected
    elif "estimated_date" in flags:
        on = relative_date(quote, corrected) or on
    else:
        return on, flags
    return on, tuple(f for f in flags if f != "ambiguous_date")


def observed_on(drafted: date | None, quote: str, dating: Dating) -> tuple[date | None, tuple[DateFlag, ...]]:
    """A drafted Fact's observed-on date and its flags (DateFlag), from the date the model gave and the quote:
    - a quote with a relative date and no date of its own: the estimate counted back from the Document date;
    - the model's date, flagged when it is a reading of an ambiguous date in the quote;
    - no date from the model: the quote's first date, read in the Document's date order;
    - no date anywhere: the Document date;
    - no Document date either: None (the Critic's MISSING_DATE)."""
    doc_date = dating.document_date
    doc_flags: tuple[DateFlag, ...] = ("ambiguous_date",) if doc_date and doc_date.ambiguous else ()
    written = dates_in(quote, dating.order)
    if doc_date and not written and (estimate := relative_date(quote, doc_date.on)):
        return estimate, ("estimated_date", *doc_flags)
    if drafted is not None:
        ambiguous = any(r.ambiguous and drafted in (r.on, r.other) for r in written)
        return drafted, ("ambiguous_date",) if ambiguous else ()
    if written:
        return written[0].on, ("ambiguous_date",) if written[0].ambiguous else ()
    if doc_date:
        return doc_date.on, ("document_date", *doc_flags)
    return None, ()
