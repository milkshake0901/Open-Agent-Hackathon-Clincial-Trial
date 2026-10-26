"""app/trials/ctgov.py — ClinicalTrials.gov access. Private to the trials module."""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import httpx

from app.ctx import Ctx
from app.trials import (Contact, LivePages, NctId, OutcomeMeasure, Outcomes, PostedResult, Publication, ResultValue,
                        SavedPages, TrialContacts, TrialSite, Trial, page_url)

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
    primary_completion_date: str | None = None
    completion_date: str | None = None
    last_update_date: str | None = None
    contacts: TrialContacts | None = None
    outcomes: Outcomes | None = None


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
                    contacts=_contacts(p), outcomes=_outcomes(study),
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
                status=loc.get("status", ""), lat=geo.get("lat"), lon=geo.get("lon"),
                contacts=tuple(map(_contact, loc.get("contacts", ()))))


def _contact(c: dict[str, Any]) -> Contact:
    return Contact(name=c.get("name", ""), role=c.get("role", ""), email=c.get("email", ""),
                   phone=c.get("phone", ""), affiliation=c.get("affiliation", ""))


def _contacts(p: dict[str, Any]) -> TrialContacts:
    """Central contacts, overall officials, lead sponsor and responsible party (#27). A responsible party of type
    SPONSOR names no person, so it is named by the lead sponsor."""
    cl = p.get("contactsLocationsModule", {})
    sc = p.get("sponsorCollaboratorsModule", {})
    sponsor = sc.get("leadSponsor", {}).get("name", "")
    rp = sc.get("responsibleParty")
    responsible = None if not rp else Contact(
        name=sponsor if rp.get("type") == "SPONSOR" else rp.get("investigatorFullName", ""), role=rp.get("type", ""),
        affiliation=rp.get("investigatorAffiliation", ""), title=rp.get("investigatorTitle", ""))
    return TrialContacts(sponsor=sponsor, responsible_party=responsible,
                         central=tuple(map(_contact, cl.get("centralContacts", ()))),
                         officials=tuple(map(_contact, cl.get("overallOfficials", ()))),
                         page_url=page_url(p["identificationModule"]["nctId"]))


def _outcomes(study: dict[str, Any]) -> Outcomes:
    """Planned outcome measures, the has-results flag, posted results and linked publications (#25)."""
    om = study["protocolSection"].get("outcomesModule", {})
    measures = lambda key: tuple(OutcomeMeasure(measure=m.get("measure", ""), description=m.get("description", ""),  # noqa: E731
                                                time_frame=m.get("timeFrame", "")) for m in om.get(key, ()))
    posted = study.get("resultsSection", {}).get("outcomeMeasuresModule", {}).get("outcomeMeasures", ())
    return Outcomes(primary=measures("primaryOutcomes"), secondary=measures("secondaryOutcomes"),
                    other=measures("otherOutcomes"), has_results=bool(study.get("hasResults")),
                    results=tuple(map(_posted, posted)),
                    publications=tuple(Publication(pmid=r.get("pmid", ""), type=r.get("type", ""),
                                                   citation=r.get("citation", ""))
                                       for r in study["protocolSection"].get("referencesModule", {}).get("references", ())))


def _posted(m: dict[str, Any]) -> PostedResult:
    """A posted outcome measure, its measurements flattened in registry order; a split measure's values are labelled
    by their class and category titles."""
    groups = {g.get("id"): g.get("title", "") for g in m.get("groups", ())}
    values = tuple(
        ResultValue(group=groups.get(x.get("groupId"), x.get("groupId", "")), value=x.get("value", ""),
                    spread=x.get("spread", ""), lower=x.get("lowerLimit", ""), upper=x.get("upperLimit", ""),
                    label=" · ".join(t for t in (c.get("title", ""), cat.get("title", "")) if t))
        for c in m.get("classes", ()) for cat in c.get("categories", ()) for x in cat.get("measurements", ()))
    return PostedResult(type=m.get("type", ""), title=m.get("title", ""), description=m.get("description", ""),
                        time_frame=m.get("timeFrame", ""), unit=m.get("unitOfMeasure", ""),
                        param_type=m.get("paramType", ""), values=values)


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


async def fetch_pages(source: LivePages, fetched_at: str) -> list[tuple[RawStudy, str]]:
    """Every study `GET /api/v2/studies?query.locn=Australia` returns, following nextPageToken to the last page,
    each dated `fetched_at`. The location filter is the API's text search, so a study it returns may still have no
    Australian site; `in_australia` decides."""
    out = []
    params: dict[str, str | int] = {"query.locn": AUSTRALIA, "pageSize": source.page_size}
    async with httpx.AsyncClient(base_url=source.base_url, timeout=source.timeout_s,
                                 transport=source.transport) as client:
        pace = _Pace(source)
        while True:
            page = await _get_page(client, params, source, pace)
            out.extend((parse_study(study), fetched_at) for study in page.get("studies", ()))
            if not (token := page.get("nextPageToken")):
                return out
            params = {**params, "pageToken": token}


class _Pace:
    """Spaces requests at least 60/requests_per_minute seconds apart, retries included."""
    def __init__(self, source: LivePages):
        self.interval, self.sleep, self.last = 60.0 / source.requests_per_minute, source.sleep, None

    async def wait(self) -> None:
        if self.last is not None and (gap := self.interval - (time.monotonic() - self.last)) > 0:
            await self.sleep(gap)
        self.last = time.monotonic()


_TRANSIENT = frozenset({429, 500, 502, 503, 504})


async def _get_page(client: httpx.AsyncClient, params: dict, source: LivePages, pace: _Pace) -> dict[str, Any]:
    for attempt in range(source.retries + 1):
        await pace.wait()
        try:
            r = await client.get("/studies", params=params)
        except httpx.TransportError:
            if attempt == source.retries:
                raise
            await source.sleep(2.0 ** attempt)
            continue
        if r.status_code not in _TRANSIENT or attempt == source.retries:
            r.raise_for_status()
            return r.json()
        await source.sleep(_retry_after(r) or 2.0 ** attempt)
    raise AssertionError("unreachable")


def _retry_after(r: httpx.Response) -> float | None:
    try:
        return float(r.headers["retry-after"])
    except (KeyError, ValueError):
        return None
