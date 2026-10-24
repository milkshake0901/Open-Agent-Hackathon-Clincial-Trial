"""app/trials/ctgov.py — ClinicalTrials.gov access. Private to the trials module."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.ctx import Ctx
from app.trials import NctId, Trial


@dataclass(frozen=True)
class RawStudy:
    """Parsed subset of the v2 study JSON. Transport type; never leaves this module."""
    nct_id: str
    title: str
    conditions: tuple[str, ...]
    status: str
    eligibility_text: str


async def fetch(ctx: Ctx, condition: str, location: str, max_trials: int) -> tuple[list[RawStudy], str]:
    """Returns (studies, source). Try Zetaris first: SELECT from views over a registered REST table
    (db/zetaris_register.sql). A REST table is one fixed URL, so `condition`/`location` are part of the registered
    endpoint, not pushed down from a WHERE clause. If Zetaris errors or paging stalls, fall back to httpx
    GET /api/v2/studies with pageToken, ≤50 req/min. The two paths produce RawStudy identically so the rest of the
    module cannot tell."""
    raise NotImplementedError


def eligibility_hash(text: str) -> str:
    """sha256 over whitespace-normalised text so cosmetic upstream edits do not trigger re-judging.
    Same rule as the one-Trial Zetaris load (NCT07680790 → ced65c98…)."""
    return hashlib.sha256(re.sub(r"\s+", " ", text).strip().encode()).hexdigest()


def to_trial(raw: RawStudy, source: str, fetched_at: str) -> Trial:
    return Trial(nct_id=NctId(raw.nct_id), title=raw.title, conditions=raw.conditions, status=raw.status,
                 eligibility_text=raw.eligibility_text, eligibility_hash=eligibility_hash(raw.eligibility_text),
                 fetched_at=fetched_at, source=source)


def parse_study(study: dict[str, Any]) -> RawStudy:
    """One v2 study (`GET /api/v2/studies/{nct}` body) → RawStudy."""
    p = study["protocolSection"]
    return RawStudy(nct_id=p["identificationModule"]["nctId"], title=p["identificationModule"]["briefTitle"],
                    conditions=tuple(p.get("conditionsModule", {}).get("conditions", ())),
                    status=p["statusModule"]["overallStatus"],
                    eligibility_text=p.get("eligibilityModule", {}).get("eligibilityCriteria", ""))


def read_snapshot(directory: Path) -> list[tuple[RawStudy, str]]:
    """Saved studies, one JSON file each: either the cached response envelope {url, fetched_at, body} or a bare
    study. Returns (study, fetched_at) in file-name order; a bare study's fetched_at is its last-update date."""
    out = []
    for path in sorted(Path(directory).glob("*.json")):
        data = json.loads(path.read_text())
        study = data.get("body", data)
        fetched_at = data.get("fetched_at") or study["protocolSection"]["statusModule"].get(
            "lastUpdatePostDateStruct", {}).get("date", "1970-01-01")
        out.append((parse_study(study), fetched_at))
    return out
