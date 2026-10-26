"""Turn a parsed referral's regions into Intake answers. Only words that are on the letter are used."""
from __future__ import annotations

import re

_MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)
_MONTH = "(?:" + "|".join(_MONTHS) + "|" + "|".join(m[:3] for m in _MONTHS) + ")"
_TREATMENT = re.compile(
    r"radiotherapy|tomotherapy|chemotherapy|\bchemo\b|immunotherapy|radioligand|"
    r"enantone|\badt\b|zytiga|taxotere|xtandi|lutetium|lu-177|olaparib|cabazitaxel|cabaxitaxel|"
    r"darolutamide|daroulutamide|niraparib|terbium|pembrolizumab|xgeva|abiraterone|enzalutamide",
    re.I,
)
_SEX = re.compile(r"\bSex:\s*([MF])\b", re.I)
_WHEN = re.compile(rf"diagnos\w+.{{0,220}}?\b({_MONTH})\s+((?:19|20)\d{{2}})", re.I | re.S)
_ON = re.compile(r"\b(?:also|currently|still)\s+on\s+([^.]{3,80})", re.I)
_GLEASON = re.compile(r"Gleason score\s+\d+(?:\s*\([^)]*\))?", re.I)
_FAMILY = re.compile(r"[^.]*family history of prostate cancer[^.]*\.", re.I)
_SUMMARY = re.compile(r"In summary, [^.]{20,500}\.", re.I)
_ATM = re.compile(r"[^.]*\bATM mutation[^.]*\.", re.I)


def prefill_answers(regions: list[tuple[str, str]]) -> dict[str, str]:
    """Questionnaire answers read off parsed regions `(kind, text)` in reading order.

    Empty when the letter does not say enough to fill a field. Birth month, postcode, travel and contact
    are left blank: a referral states an age and a hospital address, not those answers.
    """
    body = "\n".join(text.strip() for kind, text in regions if kind in {"Title", "Text"} and text.strip())
    if not body:
        return {}
    answers: dict[str, str] = {"respondent": "other"}
    sex = _SEX.search(body)
    if sex:
        answers["sex"] = "male" if sex.group(1).upper() == "M" else "female"
    when = _WHEN.search(body)
    if when:
        month = next(name for name in _MONTHS if name.lower().startswith(when.group(1).lower()[:3]))
        answers["diagnosis_when"] = f"{month} {when.group(2)}"
    diagnosis = _diagnosis(body)
    if diagnosis:
        answers["diagnosis"] = diagnosis
    treatments = _treatments(regions)
    if treatments:
        answers["treatments"] = treatments
    medicines = _medicines(body)
    if medicines:
        answers["medicines"] = medicines
    if len(answers) == 1:
        return {}
    return answers


def _diagnosis(body: str) -> str:
    parts: list[str] = []
    if re.search(r"\bCRPC\b|castration[-\s]resistant prostate|castrate resistant prostate", body, re.I):
        parts.append("Metastatic castration-resistant prostate cancer (CRPC).")
    elif re.search(r"prostate cancer", body, re.I):
        parts.append("Prostate cancer.")
    gleason = _GLEASON.search(body)
    if gleason:
        parts.append(gleason.group(0).strip() + ".")
    if re.search(r"\badenocarcinoma\b", body, re.I):
        parts.append("Adenocarcinoma.")
    family = _FAMILY.search(body)
    if family:
        parts.append(" ".join(family.group(0).split()))
    atm = _ATM.search(body)
    if atm:
        parts.append(" ".join(atm.group(0).split()))
    summary = _SUMMARY.search(body)
    if summary:
        parts.append(" ".join(summary.group(0).split()))
    return " ".join(parts)


def _treatments(regions: list[tuple[str, str]]) -> str:
    seen: list[str] = []
    for kind, text in regions:
        words = " ".join(text.split())
        if kind != "Text" or not words or not _TREATMENT.search(words) or words in seen:
            continue
        seen.append(words)
    return "\n\n".join(seen)


def _medicines(body: str) -> str:
    found = _ON.search(body)
    if not found:
        return ""
    line = " ".join(found.group(1).split()).rstrip(",")
    if re.search(r"chemo-immunotherapy was stopped", body, re.I):
        line += ". Chemo-immunotherapy has stopped."
    return line
