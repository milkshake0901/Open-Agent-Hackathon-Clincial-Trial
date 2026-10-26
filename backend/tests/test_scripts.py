"""The operator scripts in backend/scripts start from the command line, from the repo root and from backend/ (#41).

Only safe calls: --help and missing-argument usage errors. Nothing here reaches Postgres, Zetaris,
Nightshift, NVIDIA's API or ClinicalTrials.gov. The projection rebuild truncates tables on any run,
so it is only loaded, never run.
"""
from __future__ import annotations

import importlib.util
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
