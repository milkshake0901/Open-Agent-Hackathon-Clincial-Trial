"""app/record/deidentify.py — removes names, addresses, record numbers and clinician names from
page text BEFORE any model sees it (GLOSSARY: De-identification). Runs inside register_document,
so every Page stored and every Citation shown is already de-identified.

Deterministic rules, in this order: email addresses, labelled dates of birth, Medicare and record numbers
(labelled, or bare as on a letter's identity line, `P123456(7)`, and barcode, `OC.1234567`), phone numbers, street
addresses (Australian, and any line ending in a UK postcode), then names. Names are found where a document labels or
titles them ("Patient: ...", "Re: SMITH, JOHN", "Mrs ...", "Dr ...", "Signed: ..."), plus `known_names`; every later
occurrence of such a name, or of one of its words, written as found, in capitals or capitalised, is replaced across
all pages and Regions of the Document, and in its filename. Placeholders are stable within a Document: [PATIENT],
[CLINICIAN-1], [CLINICIAN-2], ... Other dates are kept: observed-on dates are clinical data."""
from __future__ import annotations

import re
from dataclasses import dataclass, replace

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
# A letter's identity line: "Re: SMITH, JOHN Age:55 ..." or "Re: Smith, John". Only the surname-first forms, so
# "Re: Follow up" is not taken for a name.
_RE_PATIENT = re.compile(r"\bRe[ \t]*:[ \t]*(?:(?:Mrs|Mr|Ms|Miss|Mx)\.?[ \t]+)?"
                         r"([A-Z][A-Z'\-]+,?[ \t]*[A-Z][A-Za-z'\-]+|[A-Z][a-z'\-]+,[ \t]*[A-Z][A-Za-z'\-]+)")
_NOT_NAMES = {"Male", "Female", "Unknown", "Other", "Not", "Known", "Patient", "Dr", "Doctor", "Prof", "The",
              "Age", "Sex", "Gender", "DOB", "Born", "MRN", "URN", "NHS", "Hospital", "Number", "No"}
_UK_POSTCODE = r"[A-Z]{1,2}\d[A-Z\d]?[ \t]+\d[A-Z]{2}\b"

_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), "[EMAIL]"),
    (re.compile(r"\b(DOB|D\.O\.B\.?|Date[ \t]+of[ \t]+birth)([ \t]*[:\-]?[ \t]*)[^\n,;]+", re.I), r"\1\2[DOB]"),
    (re.compile(r"\b(Medicare(?:[ \t]+(?:no\.?|number))?)([ \t]*[:#]?[ \t]*)[\d \t]{10,14}(?:/\d)?", re.I),
     r"\1\2[MEDICARE]"),
    (re.compile(r"\b\d{4}[ \t]?\d{5}[ \t]?\d(?:[ \t]?\d)?\b"), "[MEDICARE]"),
    (re.compile(r"\b(MRN|URN)([ \t]*[:#]?[ \t]*)[A-Z0-9][A-Z0-9-]{3,}"), r"\1\2[MRN]"),
    (re.compile(r"\b(UR(?:[ \t]+(?:no\.?|number))?|Medical[ \t]+record[ \t]+(?:no\.?|number)|"
                r"Hospital[ \t]+(?:no\.?|number))([ \t]*[:#][ \t]*)[A-Z0-9][A-Z0-9-]{3,}", re.I), r"\1\2[MRN]"),
    (re.compile(r"\b[A-Z]{1,2}\d{6,8}(?:\(\d\))?"), "[MRN]"),
    (re.compile(r"\b[A-Z]{1,3}\.\d{5,}\b"), "[MRN]"),
    (re.compile(r"(?:\+61[ \t]?|\(0\d\)[ \t]?|\b0)\d(?:[ \t-]?\d){7,8}\b"), "[PHONE]"),
    (re.compile(r"\b(Address)([ \t]*:[ \t]*)[^\n]+", re.I), r"\1\2[ADDRESS]"),
    (re.compile(r"(?:(?:[A-Z][A-Za-z'\-]*\.?|\d{1,5}[A-Za-z]?)(?:[ \t]+|,[ \t]*)){0,8}" + _UK_POSTCODE), "[ADDRESS]"),
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
        for pattern in (_LABELLED_PATIENT, _TITLED_PATIENT, _RE_PATIENT):
            for m in pattern.finditer(text):
                self.patient(m.group(m.lastindex))

    def _variants(self) -> dict[str, str]:
        """Each name word as found, then in capitals and capitalised: "Re: SMITH, JOHN" and "Mr Smith" are one name."""
        variants = dict(self.placeholder)
        for word, placeholder in self.placeholder.items():
            for variant in (word.upper(), word.capitalize()):
                variants.setdefault(variant, placeholder)
        return variants

    def scrub(self, text: str) -> str:
        if not self.placeholder:
            return text
        variants = self._variants()
        text = _TITLED_CLINICIAN.sub(lambda m: self._run(m.group(1), variants), text)
        text = _TITLED_PATIENT.sub(lambda m: self._run(m.group(1), variants), text)
        words = sorted(variants, key=len, reverse=True)
        text = re.sub(r"\b(?:" + "|".join(map(re.escape, words)) + r")\b", lambda m: variants[m.group(0)], text)
        # "[PATIENT] [PATIENT]" from a first name and surname reads as one placeholder
        return re.sub(r"(\[(?:PATIENT|CLINICIAN-\d+)\])(?:(?:[ \t]+|,[ \t]*|[ \t]*[A-Z]\.[ \t]*)\1)+", r"\1", text)

    def scrub_filename(self, name: str) -> str:
        """A filename joins words with "_" or "-" and ignores case: "john_SMITH-letter.pdf" → "PATIENT-letter.pdf"."""
        if not self.placeholder:
            return name
        by_fold: dict[str, str] = {}
        for word, placeholder in self.placeholder.items():
            by_fold.setdefault(word.casefold(), placeholder.strip("[]"))
        pattern = r"(?<![A-Za-z])(?:" + "|".join(map(re.escape, sorted(by_fold, key=len, reverse=True))) + r")(?![A-Za-z])"
        scrubbed = re.sub(pattern, lambda m: by_fold[m.group(0).casefold()], name, flags=re.I)
        return re.sub(r"(PATIENT|CLINICIAN-\d+)(?:[ _\-]+\1)+", r"\1", scrubbed)

    def _run(self, name: str, variants: dict[str, str]) -> str:
        words = _words(name)
        return variants.get(words[-1], "[NAME]") if words else "[NAME]"


def _rules(text: str) -> str:
    for pattern, placeholder in _RULES:
        text = pattern.sub(placeholder, text)
    return text


@dataclass(frozen=True)
class Deidentified:
    pages: tuple[Page, ...]
    regions: tuple[str, ...]
    filename: str


def deidentify_document(pages: tuple[Page, ...], regions: tuple[str, ...] = (), *, filename: str = "",
                        known_names: tuple[str, ...] = ()) -> Deidentified:
    """One Document in one pass: its pages (text and table cells), the text of each of its Regions, and its filename.
    A name learned anywhere in the Document is replaced everywhere in it. Running it again changes nothing."""
    texts = [*(p.text for p in pages), *regions]
    ruled = [_rules(t) for t in texts]
    tables = [tuple(tuple(tuple(_rules(c) for c in row) for row in t) for t in p.tables) for p in pages]
    names = _Names(known_names)
    for text, page_tables in zip(ruled, tables):
        names.collect(text)
        for cell in (c for t in page_tables for row in t for c in row):
            names.collect(cell)
    for text in ruled[len(pages):]:
        names.collect(text)
    scrubbed = [names.scrub(t) for t in ruled]
    return Deidentified(
        pages=tuple(replace(p, text=text, tables=tuple(tuple(tuple(names.scrub(c) for c in row) for row in t)
                                                      for t in page_tables))
                    for p, text, page_tables in zip(pages, scrubbed, tables)),
        regions=tuple(scrubbed[len(pages):]),
        filename=names.scrub_filename(_rules(filename)) if filename else filename)


def deidentify(pages: tuple[Page, ...], *, known_names: tuple[str, ...] = ()) -> tuple[Page, ...]:
    """Every page's text and table cells with identifiers replaced by placeholders (see the module docstring)."""
    return deidentify_document(pages, known_names=known_names).pages
