"""Write one run from the operator's log file (app/logfile.py, #35) as a Markdown page a judge can read: every model
call with its lane, the model that answered, its prompt and reply, and for each Trial judged, each Criterion's
decision, the Fact it cites, the Evaluator's check and what changed on a retry.

    backend/.venv/bin/python backend/scripts/export_run.py --list                 # recent runs, newest last
    backend/.venv/bin/python backend/scripts/export_run.py <run_id>               # -> docs/samples/<run_id>.md
    backend/.venv/bin/python backend/scripts/export_run.py <run_id> --out x.md --log path/to/trialmatch.jsonl

Reads the log only: no Postgres, Zetaris or Nightshift. The log holds what the model saw, which is de-identified;
read the page before committing it anyway.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import OrderedDict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import REPO_ROOT, Settings  # noqa: E402

_TRIAL = re.compile(r"^Trial (NCT\d+): (.*)$", re.M)
_CRITERION = re.compile(r"^- (NCT\d+:\S+) \[(inclusion|exclusion)\] (.*)$", re.M)
_FACT = re.compile(r'^- (fact:[0-9a-f]+) \| ([^|]+?): ([^|]*?) \| observed (\S+) \| ([^|]+?) \| quote "(.*)"$', re.M)
_REJECTED = "Your previous answer was rejected"
_CRITIC = "Your previous answer for this page had these problems"


def read_log(path: Path) -> list[dict]:
    lines = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        try:
            lines.append(json.loads(raw))
        except json.JSONDecodeError:
            continue   # a line cut off by a crash or rotation
    return lines


def runs(lines: list[dict]) -> "OrderedDict[str, list[dict]]":
    out: OrderedDict[str, list[dict]] = OrderedDict()
    for line in lines:
        if line.get("run_id"):
            out.setdefault(line["run_id"], []).append(line)
    return out


def _role(call: dict) -> str:
    parsed = call.get("parsed") or {}
    if isinstance(parsed, dict) and "results" in parsed and _TRIAL.search(call.get("user") or ""):
        return "matcher"
    if isinstance(parsed, dict) and "checks" in parsed:
        return "evaluator"
    if "Intake agent" in (call.get("system") or ""):
        return "intake"
    return "other"


def _nct(call: dict) -> str | None:
    if _role(call) == "matcher":
        return _TRIAL.search(call["user"]).group(1)
    ids = [c.get("criterion_id", "") for c in (call.get("parsed") or {}).get("checks", [])]
    ids += re.findall(r"CLAIM (NCT\d+):", call.get("user") or "")
    return ids[0].split(":")[0] if ids else None


def _cell(text: Any) -> str:
    return str(text if text is not None else "").replace("|", "\\|").replace("\n", " ")


def _block(text: Any) -> str:
    body = text if isinstance(text, str) else json.dumps(text, indent=2, ensure_ascii=False)
    return "```\n" + body.replace("```", "` ` `") + "\n```"


def _call_section(n: int, call: dict, title: str) -> list[str]:
    out = [f"#### Call {n}: {title}",
           f"Lane `{call.get('lane')}` · requested `{call.get('model_requested')}` · "
           f"answered **`{call.get('model_answered')}`** · {call.get('duration_ms')} ms · {call.get('at', '')[:19]}Z"]
    if call.get("error"):
        out.append(f"\n**Error:** {_cell(call['error'])}")
    for label, key in (("System prompt", "system"), ("User prompt", "user"), ("Reply (parsed)", "parsed")):
        value = call.get(key) if key != "parsed" else (call.get("parsed") or call.get("raw"))
        if value:
            out += ["", f"<details><summary>{label}</summary>", "", _block(value), "", "</details>"]
    return out + [""]


def _trial_section(nct: str, calls: list[dict], judged: dict | None) -> list[str]:
    matchers = [c for c in calls if _role(c) == "matcher"]
    evaluators = [c for c in calls if _role(c) == "evaluator"]
    first = matchers[0]["user"]
    title = _TRIAL.search(first).group(2)
    criteria = {m.group(1): (m.group(2), m.group(3)) for m in _CRITERION.finditer(first)}
    facts = {m.group(1): m.groups()[1:] for m in _FACT.finditer(first)}

    out = [f"### {nct}: {title}", ""]
    if judged:
        out.append(f"**Outcome: {judged.get('outcome')}** · attempts {judged.get('attempts')} · "
                   f"unsupported claims downgraded {judged.get('unsupported_downgraded')} · "
                   f"questions {judged.get('questions')} ({judged.get('respondent_questions')} for the Respondent)")
        out.append("")

    attempts = [{r["criterion_id"]: r for r in m["parsed"]["results"]} for m in matchers]
    checks = [{c["criterion_id"]: c for c in e["parsed"]["checks"]} for e in evaluators]
    out += ["| # | Kind | Criterion | Decision | Cited Fact | Matcher's reason | Evaluator |",
            "|---|---|---|---|---|---|---|"]
    for cid, (kind, text) in criteria.items():
        history = [a.get(cid) for a in attempts]
        final = next((h for h in reversed(history) if h), None) or {}
        decision = " → ".join(h["outcome"] for h in history if h)
        if len({h["outcome"] for h in history if h}) == 1:
            decision = final.get("outcome", "")
        if final.get("ask"):
            decision += f" (ask {final['ask']})"
        fact = facts.get(final.get("fact_id") or "")
        cited = f'{fact[0]}: "{fact[4]}" ({fact[3]}, {fact[2]})' if fact else ""
        verdicts = [("✓ " if c[cid]["supported"] else "✗ ") + c[cid]["reason"] for c in checks if cid in c]
        evaluator = " → ".join(v for i, v in enumerate(verdicts) if i == 0 or v != verdicts[i - 1])
        short = text if len(text) <= 120 else text[:117] + "…"
        out.append(f"| {cid.rsplit(':', 1)[-1]} | {kind} | {_cell(short)} | **{_cell(decision)}** | {_cell(cited)} "
                   f"| {_cell(final.get('rationale'))} | {_cell(evaluator)} |")
    for i, m in enumerate(matchers[1:], start=2):
        note = m["user"][m["user"].find(_REJECTED):] if _REJECTED in m["user"] else ""
        if note:
            out += ["", f"**Retry {i} was asked with:**", "", "> " + note.replace("\n", "\n> ")]
    return out + [""]


def _intake_section(calls: list[dict]) -> list[str]:
    out = ["## What was read: each draft Fact and the Region it was copied from", "",
           "The Intake agent drafts Facts from the letter's Regions; each must quote one Region (span_id). The "
           "Critic, code with no model, checks every draft (quote on the page, a date, no duplicate) and sends "
           "problems back for a retry, up to the bound.", ""]
    for n, call in enumerate(calls, start=1):
        facts = (call.get("parsed") or {}).get("facts") or []
        note = call["user"][call["user"].find(_CRITIC):] if _CRITIC in (call.get("user") or "") else ""
        out.append(f"### Attempt {n}: {len(facts)} draft Facts" + (f" · error: {_cell(call['error'])}"
                                                                   if call.get("error") else ""))
        if note:
            out += ["", "**Asked again with the Critic's findings:**", "", "> " + note.replace("\n", "\n> ")]
        if facts and (n == len(calls) or n == 1):
            out += ["", "| Subject | Value | Observed on | Region | Quote |", "|---|---|---|---|---|"]
            out += [f"| {_cell(f.get('subject'))} | {_cell(f.get('value'))} {_cell(f.get('unit') or '')} "
                    f"| {_cell(f.get('observed_on') or '—')} | `{_cell(f.get('span_id') or f.get('question'))}` "
                    f"| {_cell(f.get('quote'))} |" for f in facts]
        out.append("")
    return out


def render(run_id: str, lines: list[dict]) -> str:
    if not lines:
        raise SystemExit(f"no lines for {run_id} in the log")
    calls = [x for x in lines if x.get("step") == "llm.complete"]
    steps = [x for x in lines if x.get("step") != "llm.complete"]
    judged = {x["nct_id"]: x for x in steps if x.get("step") == "matching.trial_judged"}
    models = sorted({c.get("model_answered") for c in calls if c.get("model_answered")})

    out = [f"# Run `{run_id}`", "",
           f"{lines[0]['at'][:19]}Z → {lines[-1]['at'][:19]}Z · {len(calls)} model calls · "
           f"answered by {', '.join(f'`{m}`' for m in models) or 'no model'}", "",
           "Exported from `data/logs/trialmatch.jsonl` by `backend/scripts/export_run.py`.", "",
           "## Steps", "", "| Time (UTC) | Step | Detail |", "|---|---|---|"]
    for x in lines:
        if x.get("step") == "llm.complete":
            detail = f"{_role(x)} · lane {x.get('lane')} · {x.get('model_answered')} · {x.get('duration_ms')} ms"
        else:
            detail = ", ".join(f"{k}={json.dumps(v, ensure_ascii=False)}" for k, v in x.items()
                               if k not in ("at", "level", "logger", "step", "message", "run_id"))
        out.append(f"| {x['at'][11:23]} | `{x.get('step')}` | {_cell(detail)} |")
    out.append("")

    if intake := [c for c in calls if _role(c) == "intake"]:
        out += _intake_section(intake)

    by_trial: OrderedDict[str, list[dict]] = OrderedDict()
    for c in calls:
        if _role(c) in ("matcher", "evaluator") and (nct := _nct(c)):
            by_trial.setdefault(nct, []).append(c)
    if by_trial:
        out += ["## Why: each Criterion, its evidence and its check", "",
                "The Matcher judges each Criterion against the patient's Facts and must cite one Fact for met or "
                "not met. The Evaluator, a second prompt, checks each cited claim against the Fact read literally. "
                "A rejected claim is sent back for a retry; one still unsupported becomes unknown.", ""]
        for nct, trial_calls in by_trial.items():
            if any(_role(c) == "matcher" for c in trial_calls):
                out += _trial_section(nct, trial_calls, judged.get(nct))

    out += ["## Model calls", ""]
    for n, c in enumerate(calls, start=1):
        role = _role(c)
        title = {"matcher": f"Matcher, {_nct(c)}", "evaluator": f"Evaluator, {_nct(c)}",
                 "intake": "Intake"}.get(role, "model call")
        out += _call_section(n, c, title)
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("run_id", nargs="?", help="run id, e.g. run_c438f7…; see --list")
    p.add_argument("--list", action="store_true", help="list the runs in the log, newest last")
    p.add_argument("--log", type=Path, help="log file (default: LOG_FILE from .env)")
    p.add_argument("--out", type=Path, help="Markdown file to write (default: docs/samples/<run_id>.md)")
    args = p.parse_args(argv)
    if not args.list and not args.run_id:
        p.error("give a run_id, or --list")

    log = args.log or Path(Settings(_env_file=REPO_ROOT / ".env").log_file)
    all_runs = runs(read_log(log))
    if args.list:
        for rid, lines in all_runs.items():
            steps = sorted({x.get("step") for x in lines})
            print(f"{lines[0]['at'][:19]}Z  {rid}  {len(lines):3} lines  {', '.join(steps)}")
        return 0

    out = args.out or REPO_ROOT / "docs" / "samples" / f"{args.run_id}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(args.run_id, all_runs.get(args.run_id, [])) + "\n", encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
