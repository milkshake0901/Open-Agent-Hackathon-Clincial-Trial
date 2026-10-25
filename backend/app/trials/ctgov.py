"""app/trials/ctgov.py — ClinicalTrials.gov access. Private to the trials module."""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.ctx import Ctx
from app.trials import NctId, TrialSite, Trial

API = "https://clinicaltrials.gov/api/v2/studies"
# The site's WAF rejects some HTTP libraries. urllib uses the platform TLS stack.
_HEADERS = {"Accept": "application/json", "User-Agent": "trialmatch/0.1 (research; https://clinicaltrials.gov/data-api)"}
_FIELDS = "IdentificationModule,StatusModule,ConditionsModule,EligibilityModule,ContactsLocationsModule"
_UK = frozenset({"uk", "u.k.", "u.k", "gb", "great britain", "britain", "england"})


@dataclass(frozen=True)
class RawStudy:
    """Parsed subset of the v2 study JSON. Transport type; never leaves this module."""
    nct_id: str
    title: str
    conditions: tuple[str, ...]
    status: str
    eligibility_text: str
    sites: tuple[TrialSite, ...] = ()


class TrialsUnavailable(Exception):
    """ClinicalTrials.gov did not return studies."""


def location_for_search(location: str) -> str:
    """UK sites are indexed as United Kingdom. Other places are sent as written."""
    trimmed = location.strip()
    return "United Kingdom" if trimmed.casefold() in _UK else trimmed


def studies_url(condition: str, location: str, page_size: int, page_token: str | None = None) -> str:
    """One recruiting search. Condition and place are separate parameters, so a prior drug is not required to match."""
    params: list[tuple[str, str]] = [
        ("query.cond", condition.strip()),
        ("filter.overallStatus", "RECRUITING"),
        ("pageSize", str(page_size)),
        ("fields", _FIELDS),
        ("format", "json"),
    ]
    place = location_for_search(location)
    if place:
        params.append(("query.locn", place))
    if page_token:
        params.append(("pageToken", page_token))
    return f"{API}?{urllib.parse.urlencode(params)}"


def _get_json(url: str) -> dict:
    request = urllib.request.Request(url, headers=_HEADERS)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = response.read()
    except urllib.error.URLError as e:
        raise TrialsUnavailable(f"ClinicalTrials.gov did not answer: {e.reason}") from e
    try:
        return json.loads(body)
    except json.JSONDecodeError as e:
        raise TrialsUnavailable("ClinicalTrials.gov did not return JSON") from e


async def fetch(ctx: Ctx, condition: str, location: str, max_trials: int) -> tuple[list[RawStudy], str]:
    """Recruiting studies for this condition and place, capped at max_trials. Source is http: the query is
    built per patient, and a Zetaris REST table is one fixed URL."""
    del ctx
    if max_trials < 1:
        return [], "http"
    studies: list[RawStudy] = []
    token: str | None = None
    while len(studies) < max_trials:
        page_size = min(max_trials - len(studies), 1000)
        data = await asyncio.to_thread(_get_json, studies_url(condition, location, page_size, token))
        batch = data.get("studies") or []
        studies.extend(parse_study(study) for study in batch)
        token = data.get("nextPageToken")
        if not token or not batch:
            break
    return studies[:max_trials], "http"


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
                    eligibility_text=p.get("eligibilityModule", {}).get("eligibilityCriteria", ""),
                    sites=tuple(_site(loc) for loc in p.get("contactsLocationsModule", {}).get("locations", ())))


def _site(loc: dict[str, Any]) -> TrialSite:
    geo = loc.get("geoPoint") or {}
    return TrialSite(facility=loc.get("facility", ""), city=loc.get("city", ""), country=loc.get("country", ""),
                status=loc.get("status", ""), lat=geo.get("lat"), lon=geo.get("lon"))


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
