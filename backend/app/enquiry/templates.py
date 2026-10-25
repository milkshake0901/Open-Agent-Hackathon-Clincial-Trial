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


CLOSED_SYSTEM = """You draft an email from a patient (or their family member or carer) to the team behind a clinical trial
that has finished or stopped enrolling, asking what it found and whether there is a follow-on study. The Respondent
will edit it and send it themselves. Answer with JSON only:
{"body": "the email's paragraphs"}
- Write only the paragraphs: no subject, no greeting, no sign-off, no name. Code adds those.
- Plain, polite language a patient would use; short paragraphs; under 250 words.
- Say the patient has the condition the trial studied and would like to learn from it. Ask about its results, naming
  the outcome measures below; if results are posted, ask what they mean for someone like the patient; if not, ask
  when they will be shared.
- Ask whether a follow-on study is planned or open in Australia, and how to find out about it.
- Mention only the clinical details listed. Never invent details, results, names, dates or contact details.
"""


def _measure(m: trials.OutcomeMeasure) -> str:
    return m.measure + "".join(f" ({x})" for x in (m.time_frame,) if x)


def _value(v: trials.ResultValue) -> str:
    extra = ([f"{v.lower} to {v.upper}"] if v.lower or v.upper else []) + ([f"spread {v.spread}"] if v.spread else [])
    label = f" [{v.label}]" if v.label else ""
    return f"{v.group}{label}: {v.value}" + (f" ({', '.join(extra)})" if extra else "")


def _result(r: trials.PostedResult) -> str:
    about = ", ".join(x for x in (r.type.lower().replace("_", " "), r.param_type.lower().replace("_", " "), r.unit,
                                  r.time_frame) if x)
    return f"- {r.title} ({about}): " + "; ".join(map(_value, r.values))


def _closed_prompt(trial: trials.Trial, outcomes: trials.Outcomes | None,
                   details: tuple[ClinicalDetail, ...]) -> str:
    o = outcomes or trials.Outcomes(primary=(), secondary=(), other=())
    lines = [f"Trial {trial.nct_id}: {trial.title}",
             f"Status: {trial.status.lower().replace('_', ' ')}" + (f", finished {trial.closed_on}" if trial.closed_on
                                                                    else ""), "",
             "The patient would like to ask about its results and any follow-on study.", "",
             "Planned outcome measures:"]
    lines += [f"- [{kind}] {_measure(m)}" for kind, ms in (("primary", o.primary), ("secondary", o.secondary),
                                                          ("other", o.other)) for m in ms] or ["- (none listed)"]
    lines += ["", "Posted results:"]
    lines += [_result(r) for r in o.results] or ["- (none posted)"]
    lines += ["", "Linked publications:"]
    lines += [f"- [{p.type.lower()}] {p.citation}" for p in o.publications] or ["- (none listed)"]
    lines += ["", "Clinical details the patient chose to share:"]
    lines += [f"- {d.label}: {d.text}" for d in details] or ["- (none: do not mention any)"]
    return "\n".join(lines)


TEMPLATES: dict[str, Template] = {
    "open": Template(system=OPEN_SYSTEM, prompt=_open_prompt,
                     subject=lambda t: f"Enquiry about taking part in {t.nct_id}: {t.title}"),
    "closed": Template(system=CLOSED_SYSTEM, prompt=_closed_prompt,
                       subject=lambda t: f"Enquiry about the results of {t.nct_id}: {t.title}"),
}
