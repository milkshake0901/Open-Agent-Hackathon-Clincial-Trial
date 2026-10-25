"""app/trials/summary.py — the plain-language Outcome summary's prompt and the Outcome content hash it is cached by.
The prompt holds only what the registry published about the Trial: no patient data reaches this model call."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict

from pydantic import BaseModel

from app.trials import Outcomes, Trial


class Written(BaseModel):
    summary: str


def outcomes_hash(o: Outcomes) -> str:
    """sha256 of the Outcomes' canonical JSON: any change to a measure, result value or publication changes it."""
    return hashlib.sha256(json.dumps(asdict(o), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


SYSTEM = """You explain a finished clinical trial's outcomes to a patient (or their family member or carer) who is not
medically trained. Answer with JSON only: {"summary": "the explanation"}
- Plain, calm language a patient would use; short paragraphs; under 200 words.
- Say what the trial was trying to find out, then what it found if results are posted, in everyday words and with the
  numbers that matter. If no results are posted, say so plainly and do not guess what it found.
- Use only what is listed below. Never invent results, numbers, dates or conclusions.
- Do not give medical advice; you may suggest talking to their doctor about what it means for them.
"""


def prompt(trial: Trial, o: Outcomes) -> str:
    measures = lambda ms: [f"- {m.measure}" + (f" ({m.time_frame})" if m.time_frame else "")  # noqa: E731
                           + (f": {m.description}" if m.description else "") for m in ms] or ["- (none listed)"]
    lines = [f"Trial {trial.nct_id}: {trial.title}", f"Conditions: {', '.join(trial.conditions)}",
             f"Status: {trial.status}", "", "Main things measured:", *measures(o.primary), "",
             "Other things measured:", *measures(o.secondary + o.other), "", "Posted results:"]
    for r in o.results:
        lines.append(f"- {r.title} [{r.type}" + (f", {r.param_type}" if r.param_type else "")
                     + (f", {r.time_frame}" if r.time_frame else "") + "]" + (f": {r.description}" if r.description else ""))
        for v in r.values:
            limits = f" ({v.lower} to {v.upper})" if v.lower or v.upper else f" (spread {v.spread})" if v.spread else ""
            lines.append(f"  - {v.group}" + (f", {v.label}" if v.label else "") + f": {v.value}"
                         + (f" {r.unit}" if r.unit else "") + limits)
    if not o.results:
        lines.append("- (none posted)" + (" — the registry says results exist but they are not listed here"
                                          if o.has_results else ""))
    lines += ["", "Publications:"]
    lines += [f"- [{p.type}] {p.citation}" for p in o.publications] or ["- (none linked)"]
    return "\n".join(lines)
