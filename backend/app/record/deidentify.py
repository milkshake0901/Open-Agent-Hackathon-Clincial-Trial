"""app/record/deidentify.py — removes names, addresses, record numbers and clinician names from
page text BEFORE any model sees it (GLOSSARY: De-identification). Runs inside register_document,
so every Page stored and every Citation shown is already de-identified.

Deterministic rules, in this order: email addresses, labelled dates of birth, Medicare and record numbers,
phone numbers, street addresses, then names. Names are found where a document labels or titles them
("Patient: ...", "Mrs ...", "Dr ...", "Signed: ..."), plus `known_names`; every later occurrence of such a name,
or of one of its words, is replaced across all pages. Placeholders are stable within a Document: [PATIENT],
[CLINICIAN-1], [CLINICIAN-2], ... Other dates are kept: observed-on dates are clinical data."""
from __future__ import annotations

import re
from dataclasses import replace

from app.record.types import Page

_NAME = r"[A-Z][A-Za-z'\-]+(?:(?:[ \t]+|,[ \t]*)(?:[A-Z]\.|[A-Z][A-Za-z'\-]+)){0,3}"
_TITLED_CLINICIAN = re.compile(rf"\b(?:A/Prof|Prof(?:essor)?|Doctor|Dr)\.?[ \t]+((?:[A-Z]\.[ \t]*)*{_NAME})")
_LABELLED_CLINICIAN = re.compile(
    rf"\b((?:Referring|Treating)[ \t]+(?:doctor|clinician|physician|GP)|Consultant|Oncologist|Surgeon|Physician|GP|"
    rf"Reported[ \t]+by|Signed|Clinician|Pathologist|Radiologist)[ \t]*:[ \t]*({_NAME})")
_LABELLED_PATIENT = re.compile(
    rf"\b(Patient(?:[ \t]+name)?|Name|Surname|Family[ \t]+name|Given[ \t]+names?|First[ \t]+name)[ \t]*:[ \t]*"
    rf"({_NAME})")
_TITLED_PATIENT = re.compile(rf"\b(?:Mrs|Mr|Ms|Miss|Mx)\.?[ \t]+({_NAME})")
_NOT_NAMES = {"Male", "Female", "Unknown", "Other", "Not", "Known", "Patient", "Dr", "Doctor", "Prof", "The"}

_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), "[EMAIL]"),
    (re.compile(r"\b(DOB|D\.O\.B\.?|Date[ \t]+of[ \t]+birth)([ \t]*[:\-]?[ \t]*)[^\n,;]+", re.I), r"\1\2[DOB]"),
    (re.compile(r"\b(Medicare(?:[ \t]+(?:no\.?|number))?)([ \t]*[:#]?[ \t]*)[\d \t]{10,14}(?:/\d)?", re.I),
     r"\1\2[MEDICARE]"),
    (re.compile(r"\b\d{4}[ \t]?\d{5}[ \t]?\d(?:[ \t]?\d)?\b"), "[MEDICARE]"),
    (re.compile(r"\b(MRN|URN)([ \t]*[:#]?[ \t]*)[A-Z0-9][A-Z0-9-]{3,}"), r"\1\2[MRN]"),
    (re.compile(r"\b(UR(?:[ \t]+(?:no\.?|number))?|Medical[ \t]+record[ \t]+(?:no\.?|number)|"
                r"Hospital[ \t]+(?:no\.?|number))([ \t]*[:#][ \t]*)[A-Z0-9][A-Z0-9-]{3,}", re.I), r"\1\2[MRN]"),
    (re.compile(r"(?:\+61[ \t]?|\(0\d\)[ \t]?|\b0)\d(?:[ \t-]?\d){7,8}\b"), "[PHONE]"),
    (re.compile(r"\b(Address)([ \t]*:[ \t]*)[^\n]+", re.I), r"\1\2[ADDRESS]"),
    (re.compile(r"\b\d{1,5}[A-Za-z]?(?:/\d{1,5})?[ \t]+(?:[A-Z][a-z]+[ \t]+){1,3}(?:Street|St|Road|Rd|Avenue|Ave|"
                r"Drive|Lane|Ln|Place|Pl|Court|Ct|Crescent|Cres|Parade|Pde|Highway|Hwy|Boulevard|Blvd|Way|Close|"
                r"Terrace|Tce)\b\.?(?:,[ \t]*[A-Z][A-Za-z \t]+?(?:[ \t]+(?:NSW|VIC|QLD|SA|WA|TAS|NT|ACT))?"
                r"(?:[ \t]+\d{4})?)?"), "[ADDRESS]"),
)


def _words(name: str) -> list[str]:
    return [w for w in re.split(r"[ \t,]+", name) if len(w) > 1 and not w.endswith(".") and w not in _NOT_NAMES]


class _Names:
    """Names found in one Document → stable placeholders."""

    def __init__(self, known_names: tuple[str, ...]) -> None:
        self.placeholder: dict[str, str] = {}
        self.clinicians = 0
        for name in known_names:
            self.patient(name)

    def patient(self, name: str) -> None:
        for word in _words(name):
            self.placeholder.setdefault(word, "[PATIENT]")

    def clinician(self, name: str) -> None:
        words = _words(name)
        if not words:
            return
        surname = words[-1]
        if surname not in self.placeholder:
            self.clinicians += 1
            self.placeholder[surname] = f"[CLINICIAN-{self.clinicians}]"
        for word in words[:-1]:
            self.placeholder.setdefault(word, self.placeholder[surname])

    def collect(self, text: str) -> None:
        for m in _TITLED_CLINICIAN.finditer(text):
            self.clinician(m.group(1))
        for m in _LABELLED_CLINICIAN.finditer(text):
            self.clinician(m.group(2))
        for pattern in (_LABELLED_PATIENT, _TITLED_PATIENT):
            for m in pattern.finditer(text):
                self.patient(m.group(m.lastindex))

    def scrub(self, text: str) -> str:
        if not self.placeholder:
            return text
        text = _TITLED_CLINICIAN.sub(lambda m: self._run(m.group(1)), text)
        text = _TITLED_PATIENT.sub(lambda m: self._run(m.group(1)), text)
        words = sorted(self.placeholder, key=len, reverse=True)
        text = re.sub(r"\b(?:" + "|".join(map(re.escape, words)) + r")\b", lambda m: self.placeholder[m.group(0)], text)
        # "[PATIENT] [PATIENT]" from a first name and surname reads as one placeholder
        return re.sub(r"(\[(?:PATIENT|CLINICIAN-\d+)\])(?:(?:[ \t]+|,[ \t]*|[ \t]*[A-Z]\.[ \t]*)\1)+", r"\1", text)

    def _run(self, name: str) -> str:
        words = _words(name)
        return self.placeholder.get(words[-1], "[NAME]") if words else "[NAME]"


def _rules(text: str) -> str:
    for pattern, placeholder in _RULES:
        text = pattern.sub(placeholder, text)
    return text


def deidentify(pages: tuple[Page, ...], *, known_names: tuple[str, ...] = ()) -> tuple[Page, ...]:
    """Every page's text and table cells with identifiers replaced by placeholders (see the module docstring)."""
    ruled = [(_rules(p.text), tuple(tuple(tuple(_rules(c) for c in row) for row in t) for t in p.tables))
             for p in pages]
    names = _Names(known_names)
    for text, tables in ruled:
        names.collect(text)
        for cell in (c for t in tables for row in t for c in row):
            names.collect(cell)
    return tuple(replace(p, text=names.scrub(text),
                         tables=tuple(tuple(tuple(names.scrub(c) for c in row) for row in t) for t in tables))
                 for p, (text, tables) in zip(pages, ruled))
