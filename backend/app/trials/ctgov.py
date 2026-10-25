"""app/trials/ctgov.py — ClinicalTrials.gov access. Private to the trials module."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from app.ctx import Ctx
from app.trials import Contact, NctId, SavedPages, TrialContacts, TrialSite, Trial, page_url


@dataclass(frozen=True)
class RawStudy:
    """Parsed subset of the v2 study JSON. Transport type; never leaves this module."""
    nct_id: str
    title: str
    conditions: tuple[str, ...]
    status: str
    eligibility_text: str
    sites: tuple[TrialSite, ...] = ()
    contacts: TrialContacts | None = None


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
                    eligibility_text=p.get("eligibilityModule", {}).get("eligibilityCriteria", ""),
                    sites=tuple(_site(loc) for loc in p.get("contactsLocationsModule", {}).get("locations", ())),
                    contacts=_contacts(p))


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
