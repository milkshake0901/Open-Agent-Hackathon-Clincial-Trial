"""app/enquiry/templates.py — one template per kind of Trial: the system prompt, the user prompt and the subject line.
The model writes only the paragraphs between greeting and sign-off; code adds those, so the Respondent's name and
contact are always placeholders and the model never needs them."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel

from app import matching, trials
from app.enquiry.types import ClinicalDetail, Recipient

NAME = "[Your name]"
CONTACT = "[Your email or phone]"


class Written(BaseModel):
    body: str      # the paragraphs only: no greeting, no sign-off


@dataclass(frozen=True)
class Template:
    system: str
    prompt: Callable[..., str]
    subject: Callable[[trials.Trial], str]


def letter(to: Recipient | None, paragraphs: str) -> str:
    return f"Dear {to.name if to else 'trial team'},\n\n{paragraphs.strip()}\n\nKind regards,\n{NAME}\n{CONTACT}\n"


_PLAIN = {matching.VerdictOutcome.ELIGIBLE: "likely a fit: everything that could be checked matches",
          matching.VerdictOutcome.POSSIBLE: "may be a fit: some criteria still need checking",
          matching.VerdictOutcome.EXCLUDED: "probably not a fit: something in the record rules the trial out"}

OPEN_SYSTEM = """You draft an email from a patient (or their family member or carer) to a clinical trial's team, asking
about taking part in the trial. The Respondent will edit it and send it themselves. Answer with JSON only:
{"body": "the email's paragraphs"}
- Write only the paragraphs: no subject, no greeting, no sign-off, no name. Code adds those.
- Plain, polite language a patient would use; short paragraphs; under 250 words.
- Say the patient is interested in taking part and give the result of the eligibility check below, in plain words,
  making clear it is an automated check against the published criteria, not a decision.
- Turn every unknown criterion into a short question the team can answer (a bulleted list).
- Mention only the clinical details listed. Never invent details, names, dates or contact details.
"""


def _open_prompt(trial: trials.Trial, outcome: matching.VerdictOutcome, unknown: tuple[trials.Criterion, ...],
                 details: tuple[ClinicalDetail, ...]) -> str:
    lines = [f"Trial {trial.nct_id}: {trial.title}", "", "The patient would like to ask about taking part.", "",
             f"Eligibility check (Verdict): {outcome} ({_PLAIN[outcome]})", "",
             "Unknown criteria (turn each into a question):"]
    lines += [f"- [{c.kind}] {c.text}" for c in unknown] or ["- (none)"]
    lines += ["", "Clinical details the patient chose to share:"]
    lines += [f"- {d.label}: {d.text}" for d in details] or ["- (none: do not mention any)"]
    return "\n".join(lines)


TEMPLATES: dict[str, Template] = {
    "open": Template(system=OPEN_SYSTEM, prompt=_open_prompt,
                     subject=lambda t: f"Enquiry about taking part in {t.nct_id}: {t.title}"),
}
