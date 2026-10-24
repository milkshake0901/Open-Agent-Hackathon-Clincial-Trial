"""Phase 3 add-on: per-site distance to Sydney and per-site status for every sample → out/03b_sites.json.

The API's filter.geo keeps a study if ANY site is within the radius; the matcher needs to know WHICH site, and its own status.
"""
from __future__ import annotations

import json
import math
import statistics
from collections import Counter

import ctgov_http as h

SYDNEY = (-33.8688, 151.2093)
RADIUS_KM = 50


def km(a, b) -> float:
    (la1, lo1), (la2, lo2) = [(math.radians(x), math.radians(y)) for x, y in (a, b)]
    d = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(d))


def main() -> None:
    out = {}
    for key in ("A", "B", "C"):
        studies = json.loads((h.CACHE / f"sample_{key}.json").read_text())
        sites_total = sites_geo = 0
        near_status = Counter()
        studies_with_near = studies_with_near_recruiting = 0
        sites_per_study = []
        au_studies = 0
        for s in studies:
            locs = s["protocolSection"].get("contactsLocationsModule", {}).get("locations", [])
            sites_per_study.append(len(locs))
            sites_total += len(locs)
            near = []
            for l in locs:
                gp = l.get("geoPoint")
                if gp:
                    sites_geo += 1
                    if km(SYDNEY, (gp["lat"], gp["lon"])) <= RADIUS_KM:
                        near.append(l)
            if any(l.get("country") == "Australia" for l in locs):
                au_studies += 1
            for l in near:
                near_status[l.get("status", "(missing)")] += 1
            if near:
                studies_with_near += 1
                if any(l.get("status") in ("RECRUITING", "NOT_YET_RECRUITING") for l in near):
                    studies_with_near_recruiting += 1
        out[key] = {
            "studies": len(studies),
            "sites_total": sites_total,
            "sites_with_geoPoint_share": round(sites_geo / max(1, sites_total), 3),
            "sites_per_study_median": statistics.median(sites_per_study) if sites_per_study else 0,
            "studies_with_any_australian_site": au_studies,
            f"studies_with_site_within_{RADIUS_KM}km_sydney": studies_with_near,
            "of_those_with_a_near_site_recruiting_or_not_yet": studies_with_near_recruiting,
            "near_site_status_counts": dict(near_status),
        }
    (h.OUT / "03b_sites.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
