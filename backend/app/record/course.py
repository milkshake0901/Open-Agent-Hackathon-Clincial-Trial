"""A treatment timeline and the biomarker readings to set beside it, taken from a letter's Facts.

The dates and values are the Facts' own. A comparison may only mention a treatment and a reading that are both here.
Which marker is the key one follows the diagnosis: prostate cancer is measured with PSA.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

_NUMBER = re.compile(r"\d+(?:\.\d+)?")
# Words in the diagnosis, then the marker subjects to chart beside the treatments.
_KEY = (
    (("prostate", "psa", "crpc"), ("psa",)),
    (("breast",), ("ca 15-3", "ca15-3")),
    (("lung",), ("cea",)),
    (("myeloma",), ("light chain", "m protein")),
)
_TREATMENTS = {"Procedure", "MedicationStatement"}


@dataclass(frozen=True)
class Row:
    resource: str
    subject: str
    value: str
    unit: str | None
    on: date | None


@dataclass(frozen=True)
class Treatment:
    subject: str
    detail: str
    on: date | None


@dataclass(frozen=True)
class Reading:
    subject: str
    value: str
    number: float
    unit: str | None
    on: date


@dataclass(frozen=True)
class MarkerSeries:
    name: str
    points: tuple[Reading, ...]


@dataclass(frozen=True)
class Course:
    diagnosis: str
    marker: str | None
    treatments: tuple[Treatment, ...]
    series: tuple[MarkerSeries, ...]


@dataclass(frozen=True)
class Note:
    treatment: str
    on: str
    value: str
    change: str


@dataclass(frozen=True)
class Comparison:
    marker: str | None
    summary: str
    notes: tuple[Note, ...]


def build(rows: list[Row], diagnosis: str) -> Course:
    """Treatments in date order, and the key marker's readings. A Fact with no date stays on the timeline, last."""
    names = _markers(diagnosis)
    treatments, by_marker, seen_treatment, seen_reading = [], {}, set(), set()
    for row in rows:
        if row.resource in _TREATMENTS and row.subject.strip():
            item = Treatment(row.subject.strip(), _detail(row), row.on)
            key = (item.subject.casefold(), item.on, item.detail.casefold())
            if key not in seen_treatment:
                seen_treatment.add(key)
                treatments.append(item)
        elif row.resource == "Observation" and row.on is not None:
            name = _which(row.subject, names)
            number = _number(row.value)
            if name and number is not None:
                key = (name, row.on, number)
                if key in seen_reading:
                    continue
                seen_reading.add(key)
                by_marker.setdefault(name, []).append(
                    Reading(row.subject.strip(), row.value.strip(), number, row.unit, row.on))
    treatments.sort(key=lambda item: (item.on is None, item.on or date.min))
    series = tuple(
        MarkerSeries(name, tuple(sorted(points, key=lambda point: point.on)))
        for name, points in by_marker.items())
    marker = series[0].name if series else (names[0].upper() if names else None)
    return Course(diagnosis, marker, tuple(treatments), series)


def crowded_indexes(treatments: tuple[Treatment, ...]) -> tuple[int, ...]:
    """Indexes of treatments that share a date with another treatment. One event on a date needs no judge."""
    counts: dict[date | None, int] = {}
    for item in treatments:
        counts[item.on] = counts.get(item.on, 0) + 1
    return tuple(i for i, item in enumerate(treatments) if counts[item.on] > 1)


def merge_groups(treatments: tuple[Treatment, ...], groups: list[list[int]]) -> tuple[Treatment, ...]:
    """One event per group of indexes that share a date. A group that mixes dates, or names an index twice, is
    ignored and those rows stay as they are. The wording kept is the longest detail already on the letter."""
    used: set[int] = set()
    chosen: dict[int, Treatment] = {}
    for group in groups:
        indexes = [i for i in group if isinstance(i, int) and 0 <= i < len(treatments) and i not in used]
        if len(indexes) < 2 or len({treatments[i].on for i in indexes}) != 1:
            continue
        used.update(indexes)
        chosen[min(indexes)] = max((treatments[i] for i in indexes), key=lambda item: (len(item.detail), len(item.subject)))
    return tuple(chosen[i] if i in chosen else item for i, item in enumerate(treatments) if i not in used or i in chosen)


def ground(course: Course, summary: str, notes: list[Note]) -> Comparison:
    """Keep a note only when its treatment and its reading are both on the course."""
    labels = {item.subject.casefold() for item in course.treatments}
    readings = {(point.on.isoformat(), _number(point.value)) for series in course.series for point in series.points}
    kept = []
    for note in notes:
        if note.treatment.casefold() not in labels:
            continue
        try:
            on = date.fromisoformat(note.on[:10]).isoformat()
        except ValueError:
            continue
        if (on, _number(note.value)) not in readings:
            continue
        kept.append(Note(note.treatment, on, note.value, " ".join(note.change.split())))
    return Comparison(course.marker, " ".join(summary.split()), tuple(kept))


def _markers(diagnosis: str) -> tuple[str, ...]:
    text = diagnosis.casefold()
    for words, markers in _KEY:
        if any(word in text for word in words):
            return markers
    return ()


def _which(subject: str, markers: tuple[str, ...]) -> str | None:
    text = subject.casefold()
    for marker in markers:
        if re.search(rf"(?<![a-z0-9]){re.escape(marker)}(?![a-z0-9])", text):
            return "PSA" if marker == "psa" else marker.upper()
    return None


def _detail(row: Row) -> str:
    value = row.value.strip()
    if value and value.casefold() not in {row.subject.casefold(), "present", "yes"}:
        text = value
    else:
        text = row.subject.strip()
    return f"{text} {row.unit}".strip() if row.unit else text


def _number(value: str) -> float | None:
    found = _NUMBER.search(value.replace(",", ""))
    return float(found.group(0)) if found else None
