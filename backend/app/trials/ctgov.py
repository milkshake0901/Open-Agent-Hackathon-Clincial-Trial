"""app/trials/ctgov.py — ClinicalTrials.gov access. Private to the trials module."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from app.ctx import Ctx
from app.trials import NctId, SavedPages, TrialSite, Trial


@dataclass(frozen=True)
class RawStudy:
    """Parsed subset of the v2 study JSON. Transport type; never leaves this module."""
    nct_id: str
    title: str
    conditions: tuple[str, ...]
    status: str
    eligibility_text: str
    sites: tuple[TrialSite, ...] = ()
    primary_completion_date: str | None = None
    completion_date: str | None = None
    last_update_date: str | None = None


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
                 fetched_at=fetched_at, source=source, primary_completion_date=raw.primary_completion_date,
                 completion_date=raw.completion_date, last_update_date=raw.last_update_date)


def parse_study(study: dict[str, Any]) -> RawStudy:
    """One v2 study (`GET /api/v2/studies/{nct}` body) → RawStudy."""
    p = study["protocolSection"]
    dates = p["statusModule"]
    return RawStudy(nct_id=p["identificationModule"]["nctId"], title=p["identificationModule"]["briefTitle"],
                    conditions=tuple(p.get("conditionsModule", {}).get("conditions", ())),
                    status=p["statusModule"]["overallStatus"],
                    eligibility_text=p.get("eligibilityModule", {}).get("eligibilityCriteria", ""),
                    sites=tuple(_site(loc) for loc in p.get("contactsLocationsModule", {}).get("locations", ())),
                    primary_completion_date=_date(dates.get("primaryCompletionDateStruct")),
                    completion_date=_date(dates.get("completionDateStruct")),
                    last_update_date=_date(dates.get("lastUpdatePostDateStruct")))


def _date(struct: dict[str, Any] | None) -> str | None:
    """A v2 date struct ({"date": "2012-10"} or "2012-10-15") as an ISO date; a month-only date is its 1st."""
    day = (struct or {}).get("date")
    return None if not day else day if len(day) == 10 else f"{day}-01" if len(day) == 7 else f"{day}-01-01"


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


AUSTRALIA = "Australia"   # the v2 API's country name; also the `query.locn` filter the live source pages by


def in_australia(raw: RawStudy) -> RawStudy:
    """The study with only its Australian Trial sites (ADR 0004); no sites left means it is not a Trial."""
    return replace(raw, sites=tuple(s for s in raw.sites if s.country == AUSTRALIA))


def read_pages(source: SavedPages) -> list[tuple[RawStudy, str]]:
    """Saved `GET /api/v2/studies` responses, one page per JSON file: either the cached response envelope
    {url, fetched_at, body} or a bare body {studies, nextPageToken}. Returns (study, fetched_at) in file-name then
    page order; a bare page's studies are dated by their last-update date, as in read_snapshot."""
    out = []
    for path in sorted(Path(source.directory).glob("*.json")):
        data = json.loads(path.read_text())
        page = data.get("body", data)
        for study in page.get("studies", ()):
            fetched_at = data.get("fetched_at") or study["protocolSection"]["statusModule"].get(
                "lastUpdatePostDateStruct", {}).get("date", "1970-01-01")
            out.append((parse_study(study), fetched_at))
    return out
