"""The operator scripts in backend/scripts start from the command line, from the repo root and from backend/ (#41).

Only safe calls: --help and missing-argument usage errors. Nothing here reaches Postgres, Zetaris,
Nightshift, NVIDIA's API or ClinicalTrials.gov. The projection rebuild truncates tables on any run,
so it is only loaded, never run.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.config import REPO_ROOT

BACKEND = Path(__file__).resolve().parents[1]
SCRIPTS = BACKEND / "scripts"
DIRECTORIES = pytest.mark.parametrize("cwd", [REPO_ROOT, BACKEND], ids=["repo-root", "backend"])


def run(script: str, *args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / script), *args],
        cwd=cwd, capture_output=True, text=True, timeout=60,
    )


def load(script: str):
    spec = importlib.util.spec_from_file_location(f"script_{Path(script).stem}", SCRIPTS / script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@DIRECTORIES
def test_ingest_help_shows_its_options(cwd):
    done = run("ingest_trials.py", "--help", cwd=cwd)
    assert done.returncode == 0, done.stderr
    assert done.stdout.startswith("usage: ingest_trials.py [-h] (--live | --pages PAGES)")
    assert "backend/.venv/bin/python backend/scripts/ingest_trials.py --live" in done.stdout


@DIRECTORIES
def test_nightshift_check_help_lists_its_subcommands(cwd):
    done = run("meterless.py", "--help", cwd=cwd)
    assert done.returncode == 0, done.stderr
    assert done.stdout.startswith("usage: meterless.py [-h] {status,detect,chat,lane,media,illustrate} ...")
    assert "backend/.venv/bin/python backend/scripts/meterless.py status" in done.stdout


@DIRECTORIES
@pytest.mark.parametrize("script", ["extract_document.py", "load_referral.py"])
def test_document_scripts_without_a_file_print_usage_and_exit_2(script, cwd):
    done = run(script, cwd=cwd)
    assert done.returncode == 2
    assert done.stdout + done.stderr == f"usage: {script} FILE.pdf\n"


def test_projection_rebuild_loads_without_running():
    assert callable(load("rebuild_projections.py").main)


@pytest.mark.xfail(strict=True, raises=ImportError, reason="imports app.trials.sync, which no longer exists")
def test_referral_screening_loads():
    load("screen_referral.py")


@DIRECTORIES
def test_letter_deidentification_help_offers_a_dry_run(cwd):
    done = run("deidentify_letters.py", "--help", cwd=cwd)
    assert done.returncode == 0, done.stderr
    assert done.stdout.startswith("usage: deidentify_letters.py [-h] [--dry-run]")
    assert "backend/.venv/bin/python backend/scripts/deidentify_letters.py --dry-run" in done.stdout


def _matcher(at: str, outcome: str, retry_note: str = "") -> dict:
    return {"at": at, "step": "llm.complete", "run_id": "run_x", "lane": "deep", "model_requested": "nemo",
            "model_answered": "nemo", "duration_ms": 10, "error": None, "system": "You are the Matcher.",
            "user": "Trial NCT1: A trial\n\nCriteria:\n- NCT1:h:1 [exclusion] Pregnant\n\nFacts:\n"
                    '- fact:ab | pregnant: no | observed 2026-10-27 | intake questionnaire, Q14 | quote "No"' + retry_note,
            "parsed": {"results": [{"criterion_id": "NCT1:h:1", "outcome": outcome,
                                    "fact_id": "fact:ab" if outcome != "unknown" else None, "rationale": "Says no."}]}}


def _evaluator(at: str, supported: bool) -> dict:
    return {"at": at, "step": "llm.complete", "run_id": "run_x", "lane": "judge", "model_requested": "nemo",
            "model_answered": "nemo", "duration_ms": 5, "error": None, "system": "You are the Evaluator.",
            "user": "CLAIM NCT1:h:1 | criterion (exclusion): Pregnant | claimed: not_met",
            "parsed": {"checks": [{"criterion_id": "NCT1:h:1", "supported": supported, "reason": "Fact says no."}]}}


def test_export_run_shows_each_criterion_its_cited_fact_the_evaluator_check_and_the_retry(tmp_path):
    log = tmp_path / "trialmatch.jsonl"
    lines = [
        {"at": "2026-10-27T02:00:00+00:00", "step": "matching.rescan.started", "run_id": "run_x", "to_judge": ["NCT1"]},
        _matcher("2026-10-27T02:00:01+00:00", "not_met"),
        _evaluator("2026-10-27T02:00:02+00:00", False),
        _matcher("2026-10-27T02:00:03+00:00", "unknown",
                 "\n\nYour previous answer was rejected for these Criteria. Fix them:\n- criterion NCT1:h:1: no."),
        {"at": "2026-10-27T02:00:04+00:00", "step": "matching.trial_judged", "run_id": "run_x", "nct_id": "NCT1",
         "outcome": "possible", "attempts": 2},
        {"at": "2026-10-27T02:00:05+00:00", "step": "zetaris.sql", "sql": "select 1"},   # another run's line
    ]
    log.write_text("\n".join(json.dumps(x) for x in lines) + "\n{cut off", encoding="utf-8")
    out = tmp_path / "run.md"

    assert load("export_run.py").main(["run_x", "--log", str(log), "--out", str(out)]) == 0

    page = out.read_text()
    assert "answered by `nemo`" in page and "3 model calls" in page
    assert "**Outcome: possible** · attempts 2" in page
    assert '| 1 | exclusion | Pregnant | **not_met → unknown** |  | Says no. | ✗ Fact says no. |' in page
    assert "> Your previous answer was rejected for these Criteria." in page
    assert "select 1" not in page


@DIRECTORIES
def test_export_run_without_a_run_id_or_list_prints_usage_and_exits_2(cwd):
    done = run("export_run.py", cwd=cwd)
    assert done.returncode == 2
    assert "give a run_id, or --list" in done.stderr
