"""app/record/questionnaire.py — the Intake questionnaire as data, its rendering to a Document, and the
code mapping from structured answers to DraftFacts (ADR 0003). No I/O, no model.

The definition is channel-neutral: nothing here assumes a page-based form, so a chat bot can ask the
same questions one at a time. Every question can be skipped. Never asked: name, full date of birth,
street address, labs, biomarkers, stage, histology, contraception.

`use` says where an answer goes:
  fact        structured; mapped to a Patient-reported Fact here, in code
  free_text   rendered into the Document; the Intake agent drafts Facts from it (free_text_pages)
  respondent  who is answering; stored with the Document, never a Fact
  preference  search preference (postcode, travel); never rendered, never a Fact, never seen by a model
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import date
from typing import Any, Literal

from app.record import postcodes
from app.record.types import DraftFact, FactResource, Page, Respondent

DEFINITION_VERSION = "1"
DOCUMENT_FILENAME = "Intake questionnaire"

QuestionKind = Literal["month_year", "single", "multi", "text", "textarea", "repeat"]
QuestionUse = Literal["fact", "free_text", "respondent", "preference"]


@dataclass(frozen=True)
class Option:
    value: str
    label: str


@dataclass(frozen=True)
class Question:
    id: str
    number: int                      # "Q3" in Citations
    label: str                       # wording when the patient answers ("your")
    label_other: str                 # wording when someone answers on their behalf ("their")
    kind: QuestionKind
    use: QuestionUse
    options: tuple[Option, ...] = ()
    required: bool = False
    help: str | None = None

    @property
    def ref(self) -> str:
        return f"Q{self.number}"

    def wording(self, respondent: Respondent) -> str:
        return self.label if respondent == "patient" else self.label_other


@dataclass(frozen=True)
class Section:
    id: str
    title: str
    questions: tuple[Question, ...]


@dataclass(frozen=True)
class Questionnaire:
    version: str
    sections: tuple[Section, ...]

    def questions(self) -> tuple[Question, ...]:
        return tuple(q for s in self.sections for q in s.questions)


YES_NO = (Option("yes", "Yes"), Option("no", "No"))
YES_NO_PREFER_NOT = YES_NO + (Option("prefer_not_to_say", "Prefer not to say"),)

DEFINITION = Questionnaire(DEFINITION_VERSION, (
    Section("who", "Who is answering", (
        Question("respondent", 1, "Who is filling in this questionnaire?", "Who is filling in this questionnaire?",
                 "single", "respondent",
                 (Option("patient", "I'm the patient"), Option("other", "I'm answering for someone else"))),
    )),
    Section("about", "About you", (
        Question("birth_month", 2, "What year and month were you born?", "What year and month were they born?",
                 "month_year", "fact", help="Year and month only, for example 1958-03."),
        Question("sex", 3, "What was your sex assigned at birth?", "What was their sex assigned at birth?",
                 "single", "fact",
                 (Option("female", "Female"), Option("male", "Male"), Option("intersex", "Intersex"),
                  Option("prefer_not_to_say", "Prefer not to say"))),
    )),
    Section("where", "Where you live", (
        Question("postcode", 4, "What is your postcode?", "What is their postcode?", "text", "preference",
                 help="Used only to work out distances to trial sites."),
        Question("max_travel_km", 5, "How far would you travel for a trial?", "How far would they travel for a trial?",
                 "single", "preference",
                 (Option("10", "10 km"), Option("25", "25 km"), Option("50", "50 km"), Option("100", "100 km"),
                  Option("anywhere", "Anywhere in Australia"))),
    )),
    Section("diagnosis", "Diagnosis", (
        Question("diagnosis", 6, "What is your diagnosis, in your own words?",
                 "What is their diagnosis, in your own words?", "textarea", "free_text"),
        Question("diagnosis_when", 7, "When were you diagnosed?", "When were they diagnosed?", "text", "free_text",
                 help='A rough answer such as "around March 2024" is fine.'),
    )),
    Section("treatment", "Treatment so far", (
        Question("treatments", 8, "What treatments have you had, and roughly when?",
                 "What treatments have they had, and roughly when?", "textarea", "free_text",
                 help="For example chemotherapy, radiotherapy, surgery, immunotherapy or targeted therapy. "
                      'Rough dates such as "chemo ended around March 2025" are fine.'),
    )),
    Section("medicines", "Medicines now", (
        Question("medicines", 9, "What medicines do you take now?", "What medicines do they take now?",
                 "textarea", "free_text", help="One per line. Include the dose if you know it."),
    )),
    Section("allergies", "Allergies", (
        Question("has_allergies", 10, "Do you have any allergies?", "Do they have any allergies?", "single", "fact",
                 YES_NO),
        Question("allergies", 11, "What are you allergic to?", "What are they allergic to?", "textarea", "free_text",
                 help="And what happens, for example a rash."),
    )),
    Section("other_health", "Other health", (
        Question("other_illnesses", 12, "Do you have any other major illnesses?",
                 "Do they have any other major illnesses?", "textarea", "free_text",
                 help="For example heart, kidney or liver disease, or an infection."),
    )),
    Section("daily_activity", "Daily activity", (
        Question("daily_activity", 13, "Which best describes your usual day?", "Which best describes their usual day?",
                 "single", "fact", (
                     Option("fully_active", "Fully active, doing everything as before the illness"),
                     Option("light_activity", "Can't do heavy physical work, but can do light work such as housework"),
                     Option("self_care", "Up and about more than half the day and can self-care, but can't work"),
                     Option("limited_self_care", "In a bed or chair more than half the day; limited self-care"),
                     Option("bed_bound", "In a bed or chair all day; needs help with self-care"),
                 )),
    )),
    Section("pregnancy", "Pregnancy", (
        Question("pregnancy", 14, "Are you currently pregnant, breastfeeding or planning a pregnancy?",
                 "Are they currently pregnant, breastfeeding or planning a pregnancy?", "single", "fact",
                 YES_NO_PREFER_NOT, help="Optional."),
    )),
    Section("contact", "Staying in touch", (
        Question("contact", 15, "If you'd like to hear when there are new questions to answer, leave an email or phone number.",
                 "If you'd like to hear when there are new questions to answer, leave an email or phone number.",
                 "text", "preference",
                 help="Optional. Used only to tell you there is something new to look at, never to identify the patient."),
    )),
))

# Structured question → (resource, subject). Options listed here are answered but make no Fact.
_FACTS: dict[str, tuple[FactResource, str]] = {
    "birth_month": (FactResource.PATIENT, "birth month"),
    "sex": (FactResource.PATIENT, "sex assigned at birth"),
    "has_allergies": (FactResource.ALLERGY_INTOLERANCE, "any allergy"),
    "daily_activity": (FactResource.OBSERVATION, "daily activity"),
    "pregnancy": (FactResource.OBSERVATION, "pregnant, breastfeeding or planning a pregnancy"),
}
_NO_FACT_VALUES = {"prefer_not_to_say"}
_NOT_ANSWERED = "(not answered)"
_POSTCODE = re.compile(r"^\d{4}$")     # Australian
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE = re.compile(r"^\+?[\d ()-]+$")
_MONTH = re.compile(r"^(\d{4})-(\d{2})$")
_MONTHS = ("January February March April May June July August September October November December").split()


@dataclass(frozen=True)
class SubmittedAnswers:
    """A submission read back from its Document, to prefill an edit. Preferences (postcode, travel) are not
    in the Document, so they are never here."""
    document_hash: str
    respondent: Respondent
    answers: dict[str, Any]   # question id → value, in the shape submit_questionnaire takes


class InvalidAnswers(ValueError):
    """An answer that does not fit its question (unknown id, unknown option, malformed month)."""


def _by_id() -> dict[str, Question]:
    return {q.id: q for q in DEFINITION.questions()}


def _answer_text(q: Question, value: Any) -> str:
    """The Respondent's answer as it appears on the Document page; a Fact's quote is exactly this."""
    if q.kind == "month_year":
        m = _MONTH.match(str(value))
        if not m or not 1 <= int(m.group(2)) <= 12:
            raise InvalidAnswers(f"{q.id}: expected YYYY-MM, got {value!r}")
        return f"{_MONTHS[int(m.group(2)) - 1]} {m.group(1)}"
    if q.kind == "single":
        option = next((o for o in q.options if o.value == value), None)
        if option is None:
            raise InvalidAnswers(f"{q.id}: {value!r} is not one of {[o.value for o in q.options]}")
        return option.label
    if not isinstance(value, str):
        raise InvalidAnswers(f"{q.id}: expected text")
    return " ".join(value.split())


def normalise(answers: dict[str, Any]) -> dict[str, Any]:
    """Drop skipped answers; reject unknown ids and values. Respondent and preferences are not kept."""
    questions = _by_id()
    unknown = sorted(set(answers) - set(questions))
    if unknown:
        raise InvalidAnswers(f"unknown questions: {unknown}")
    kept = {}
    for qid, value in answers.items():
        q = questions[qid]
        if q.use in ("respondent", "preference") or value is None or (isinstance(value, str) and not value.strip()):
            continue
        _answer_text(q, value)
        kept[qid] = value
    return kept


def preferences(answers: dict[str, Any]) -> dict[str, Any]:
    """The answered search preferences, validated, as SearchPreferences field → value. A skipped preference
    is absent (so a resubmission keeps what was stored); "anywhere" is an answered travel limit of None.
    An answered postcode brings its coarse `location` point with it (None if the table does not list it)."""
    normalise(answers)
    got: dict[str, Any] = {}
    for qid in ("postcode", "max_travel_km", "contact"):
        value = answers.get(qid)
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        if not isinstance(value, str):
            raise InvalidAnswers(f"{qid}: expected text")
        value = value.strip()
        if qid == "postcode" and not _POSTCODE.match(value):
            raise InvalidAnswers("postcode: expected 4 digits")
        if qid == "max_travel_km":
            _answer_text(_by_id()[qid], value)
            got[qid] = None if value == "anywhere" else int(value)
            continue
        if qid == "contact" and not (_EMAIL.match(value) or (_PHONE.match(value)
                                                             and 8 <= sum(c.isdigit() for c in value) <= 15)):
            raise InvalidAnswers("contact: expected an email or a phone number")
        got[qid] = value
        if qid == "postcode":
            got["location"] = postcodes.point(value)
    return got


def _pages(answers: dict[str, Any], respondent: Respondent, uses: tuple[QuestionUse, ...],
           answered_only: bool) -> tuple[Page, ...]:
    """Pages numbered as in the full Document (one per section with fact or free-text questions), keeping only
    the questions with a use in `uses`. Sections left with no question are dropped from the result."""
    answers = normalise(answers)
    pages = []
    number = 0
    for section in DEFINITION.sections:
        qs = [q for q in section.questions if q.use in ("fact", "free_text")]
        if not qs:
            continue
        number += 1
        shown = [q for q in qs if q.use in uses and (q.id in answers or not answered_only)]
        if not shown:
            continue
        lines = [f"Intake questionnaire: {section.title}"]
        for q in shown:
            answer = _answer_text(q, answers[q.id]) if q.id in answers else _NOT_ANSWERED
            lines += [f"{q.ref}. {q.wording(respondent)}", f"Answer: {answer}"]
        pages.append(Page(number=number, text="\n".join(lines)))
    return tuple(pages)


def render(answers: dict[str, Any], respondent: Respondent) -> tuple[Page, ...]:
    """One page per section that goes into the Document, every question listed with its number."""
    return _pages(answers, respondent, ("fact", "free_text"), answered_only=False)


def free_text_pages(answers: dict[str, Any], respondent: Respondent) -> tuple[Page, ...]:
    """What the Intake agent reads: only the answered free-text questions, each page keeping its Document page
    number so the Agent's citations point into the full Document. No structured answer, preference or
    Respondent choice is in it. Empty when no free-text question was answered (then no model call is made)."""
    return _pages(answers, respondent, ("free_text",), answered_only=True)


# Free-text question → the resource its Facts always have, whatever the model proposed.
_FREE_TEXT_RESOURCES: dict[str, FactResource] = {"allergies": FactResource.ALLERGY_INTOLERANCE}


def settle_free_text(draft: DraftFact) -> DraftFact:
    """Code has the last word on what a free-text answer is about: an allergy answer is an AllergyIntolerance."""
    q = next((q for q in DEFINITION.questions() if q.ref == draft.question), None)
    resource = _FREE_TEXT_RESOURCES.get(q.id) if q else None
    return replace(draft, resource=resource) if resource else draft


def structured_drafts(answers: dict[str, Any], respondent: Respondent, pages: tuple[Page, ...],
                      submitted_on: date) -> tuple[DraftFact, ...]:
    """Structured answers → DraftFacts, in code. Quote = the answer text; page = the question's section page.
    Answers about the present are observed on the submission date."""
    answers = normalise(answers)
    questions = _by_id()
    drafts = []
    for qid, (resource, subject) in _FACTS.items():
        value = answers.get(qid)
        if value is None or value in _NO_FACT_VALUES:
            continue
        q = questions[qid]
        page = next(p for p in pages if f"{q.ref}. " in p.text)
        drafts.append(DraftFact(resource=resource, subject=subject, value=str(value), unit=None,
                                observed_on=submitted_on, page=page.number, quote=_answer_text(q, value),
                                question=q.ref))
    return tuple(drafts)



def answers_from_pages(pages: tuple[Page, ...]) -> dict[str, Any]:
    """The inverse of render for the answers it keeps: each "Answer:" line under its question number.
    Free text comes back with whitespace collapsed, as the Document shows it."""
    by_ref = {q.ref: q for q in DEFINITION.questions()}
    answers: dict[str, Any] = {}
    for page in pages:
        lines = page.text.split("\n")
        for line, nxt in zip(lines, lines[1:]):
            q = by_ref.get(line.split(". ", 1)[0])
            if q is None or not nxt.startswith("Answer: ") or nxt == f"Answer: {_NOT_ANSWERED}":
                continue
            text = nxt.removeprefix("Answer: ")
            if q.kind == "month_year":
                month, year = text.split(" ")
                answers[q.id] = f"{year}-{_MONTHS.index(month) + 1:02d}"
            elif q.kind == "single":
                answers[q.id] = next(o.value for o in q.options if o.label == text)
            else:
                answers[q.id] = text
    return answers
