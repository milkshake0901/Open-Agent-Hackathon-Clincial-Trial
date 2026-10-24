"""app/matching/distance.py — the patient's coarse location point → km to each Trial site. Private to matching.

The postcode never reaches here (ADR 0003): record stores its coarse point with the Search preferences, and distance
reads only that point; what leaves is "site name, status, km".
Distance ranks Verdicts and flags Trials beyond the travel limit; it never changes a Verdict.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import asin, cos, radians, sin, sqrt

from app import record, trials
from app.ctx import Ctx
from app.matching.types import TrialSiteDistance
from app.trials import NctId, TrialSite

EARTH_KM = 6371.0088
CLOSED_SITE = {"WITHDRAWN", "TERMINATED", "COMPLETED", "SUSPENDED"}   # listed sites that will never take the patient
RECRUITING = "RECRUITING"


@dataclass(frozen=True)
class Origin:
    """Where distances are measured from (never the postcode itself) and the patient's travel limit."""
    point: tuple[float, float] | None     # None: no postcode, or one not in the table → "distance unknown"
    max_km: int | None                    # None: no limit


@dataclass(frozen=True)
class Reach:
    sites: tuple[TrialSiteDistance, ...]       # open sites, nearest first (unknown distances last)
    nearest_recruiting: TrialSiteDistance | None
    further_away: bool                    # a travel limit is set and no recruiting site lies within it


async def origin(ctx: Ctx, patient_id: record.PatientId) -> Origin:
    prefs = await record.search_preferences(ctx, patient_id)
    return Origin(point=prefs.location, max_km=prefs.max_travel_km)


def km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle (haversine) distance."""
    (la1, lo1), (la2, lo2) = ((radians(x), radians(y)) for x, y in (a, b))
    h = sin((la2 - la1) / 2) ** 2 + cos(la1) * cos(la2) * sin((lo2 - lo1) / 2) ** 2
    return 2 * EARTH_KM * asin(sqrt(h))


def _status(raw: str) -> str:
    return raw.replace("_", " ").lower() if raw else "status unknown"


def _name(s: TrialSite) -> str:
    return ", ".join(p for p in (s.facility, s.city, s.country) if p) or "Unnamed site"


def reach(sites: tuple[TrialSite, ...], at: Origin) -> Reach:
    measured = []
    for s in sites:
        if s.status in CLOSED_SITE:
            continue
        d = round(km(at.point, (s.lat, s.lon))) if at.point and s.lat is not None and s.lon is not None else None
        measured.append((s.status == RECRUITING, TrialSiteDistance(name=_name(s), status=_status(s.status), km=d)))
    measured.sort(key=lambda m: (m[1].km is None, m[1].km or 0, not m[0], m[1].name))
    known_recruiting = [sd for recruiting, sd in measured if recruiting and sd.km is not None]
    nearest = known_recruiting[0] if known_recruiting else next((sd for r, sd in measured if r), None)
    locatable = any(sd.km is not None for _, sd in measured)
    further = (at.max_km is not None and locatable
               and not any(sd.km <= at.max_km for sd in known_recruiting))
    return Reach(sites=tuple(sd for _, sd in measured), nearest_recruiting=nearest, further_away=further)


async def reach_of(ctx: Ctx, nct_id: NctId, at: Origin) -> Reach:
    return reach(await trials.sites(ctx, nct_id), at)


def line(sd: TrialSiteDistance) -> str:
    """The one way a site is shown to a model: "site name · status · km"."""
    return f"{sd.name} · {sd.status} · {f'{sd.km} km' if sd.km is not None else 'distance unknown'}"
