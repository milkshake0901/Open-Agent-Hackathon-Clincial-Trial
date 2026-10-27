"""Questionnaire answers a letter's drafted Facts can fill. Preferences, birth month and contact stay blank:
the letter is not where those come from."""
from __future__ import annotations

import re
from datetime import date

_PAST = re.compile(r"\b(stop|stopped|ceased|discontinued|completed|previous|prior|finished|ended)\b", re.I)
_ABSENT = {"absent", "no", "none", "nil", "no known allergies", "nkda", "nil known"}
_SEX = {"m": "male", "male": "male", "f": "female", "female": "female", "intersex": "intersex"}


def from_drafts(drafts: list[dict]) -> dict[str, str]:
    """The answers those Facts support. A Fact marked absent, and anything that is not a diagnosis, treatment,
    medicine, allergy or sex, is left out."""
    answers: dict[str, str] = {}
    conditions, treatments, medicines, allergies = [], [], [], []
    for draft in drafts:
        resource = draft.get("resource")
        if resource == "Condition":
            line = _phrase(draft)
            if line:
                conditions.append(line)
        elif resource == "Procedure":
            line = _line(draft)
            if line:
                treatments.append(line)
        elif resource == "MedicationStatement":
            line = _line(draft)
            if not line:
                continue
            (treatments if _PAST.search(f"{draft.get('value') or ''} {draft.get('subject') or ''}") else medicines).append(line)
        elif resource == "AllergyIntolerance":
            allergies.append(draft)
        elif resource == "Patient" and "sex" in str(draft.get("subject") or "").lower():
            sex = _SEX.get(str(draft.get("value") or "").strip().lower())
            if sex:
                answers["sex"] = sex
    if conditions:
        answers["diagnosis"] = "\n".join(_unique(conditions))
        when = _earliest(drafts, "Condition")
        if when:
            answers["diagnosis_when"] = when
    if treatments:
        answers["treatments"] = "\n".join(_unique(treatments))
    if medicines:
        answers["medicines"] = "\n".join(_unique(medicines))
    allergy = _allergies(allergies)
    answers.update(allergy)
    return answers


def _phrase(draft: dict) -> str:
    value = str(draft.get("value") or "").strip()
    subject = str(draft.get("subject") or "").strip()
    if value and value.lower() not in {subject.lower(), "present", "yes"}:
        return value
    return subject


def _line(draft: dict) -> str:
    subject = str(draft.get("subject") or "").strip()
    value = str(draft.get("value") or "").strip()
    if value and subject and value.lower() not in {subject.lower(), "present", "yes"}:
        text = f"{subject}: {value}"
    else:
        text = value or subject
    unit = draft.get("unit")
    if unit:
        text = f"{text} {unit}".strip()
    when = _when(draft.get("observed_on"))
    return f"{text} ({when})" if text and when else text


def _when(raw) -> str | None:
    on = raw if isinstance(raw, date) else None
    if isinstance(raw, str) and raw:
        try:
            on = date.fromisoformat(raw[:10])
        except ValueError:
            return None
    if on is None:
        return None
    return f"{on.day} {on.strftime('%B %Y')}"


def _earliest(drafts: list[dict], resource: str) -> str | None:
    parsed = []
    for d in drafts:
        if d.get("resource") != resource:
            continue
        raw = d.get("observed_on")
        try:
            parsed.append(raw if isinstance(raw, date) else date.fromisoformat(str(raw)[:10]))
        except (TypeError, ValueError):
            continue
    if not parsed:
        return None
    return _when(min(parsed))


def _allergies(drafts: list[dict]) -> dict[str, str]:
    if not drafts:
        return {}
    real = [d for d in drafts if str(d.get("value") or "").strip().lower() not in _ABSENT]
    if not real:
        return {"has_allergies": "no"}
    lines = [_line(d) for d in real]
    return {"has_allergies": "yes", "allergies": "\n".join(_unique(line for line in lines if line))}


def _unique(lines) -> list[str]:
    seen, out = set(), []
    for line in lines:
        if line not in seen:
            seen.add(line)
            out.append(line)
    return out
