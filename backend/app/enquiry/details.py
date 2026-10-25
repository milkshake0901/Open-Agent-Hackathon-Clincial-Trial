"""app/enquiry/details.py — the clinical details an Enquiry offers: the Profile version's current Facts, each in one
de-identified line. Birth month is offered as an age, never as the month itself; Search preferences are never Facts,
so the postcode and contact are never offered."""
from __future__ import annotations

from datetime import date

from app import record
from app.enquiry.types import ClinicalDetail

BIRTH_MONTH = "birth month"


def _age(birth_month: str, today: date) -> int | None:
    try:
        year, month = (int(x) for x in birth_month.split("-")[:2])
    except ValueError:
        return None
    return today.year - year - (today.month < month)


def _detail(f: record.Fact, today: date) -> ClinicalDetail | None:
    if f.subject == BIRTH_MONTH:
        age = _age(f.value, today)
        return ClinicalDetail(id=f.id, label="Age", text=f"{age} years") if age is not None else None
    if f.question is not None:   # Patient-reported: the Respondent's answer reads better than its code
        text = f.quote
    else:
        text = f"{f.value} {f.unit}" if f.unit else f.value
        text += f" ({f.observed_on.isoformat()})"
    return ClinicalDetail(id=f.id, label=f.subject[:1].upper() + f.subject[1:], text=record.deidentify_text(text))


def offered(profile: record.ProfileVersion, today: date) -> tuple[ClinicalDetail, ...]:
    return tuple(d for f in profile.current().values() if (d := _detail(f, today)) is not None)
