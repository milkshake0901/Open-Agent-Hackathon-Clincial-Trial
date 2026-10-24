"""Phase 5 helper: reference values from the raw JSON of the exact page 05_zetaris_probe.sql registers.

Writes out/zetaris_expected.csv (per study) and out/zetaris_expected.json (expected row count per probe view), so each
view's count and the eligibilityCriteria length (truncation check) can be compared with what Zetaris returns.
"""
from __future__ import annotations

import csv
import json
import urllib.parse

import ctgov_http as h

PARAMS = {
    "query.cond": "non-small cell lung cancer",
    "filter.overallStatus": "RECRUITING|NOT_YET_RECRUITING",
    "filter.geo": "distance(-33.8688,151.2093,50km)",
    "pageSize": 100,
}


def main() -> None:
    page = h.get("/studies", PARAMS)
    studies = page["studies"]
    rows = []
    for s in studies:
        p = s["protocolSection"]
        e = p.get("eligibilityModule", {})
        locs = p.get("contactsLocationsModule", {}).get("locations", [])
        ivs = p.get("armsInterventionsModule", {}).get("interventions", [])
        cb = s.get("derivedSection", {}).get("conditionBrowseModule", {})
        rows.append({
            "nct_id": p["identificationModule"]["nctId"],
            "eligibility_len": len(e.get("eligibilityCriteria", "")),
            "conditions": len(p.get("conditionsModule", {}).get("conditions", [])),
            "std_ages": len(e.get("stdAges", [])),
            "phases": len(p.get("designModule", {}).get("phases", [])),
            "locations": len(locs),
            "locations_with_geo": sum(1 for l in locs if l.get("geoPoint")),
            "interventions": len(ivs),
            "intervention_other_names": sum(len(i.get("otherNames", [])) for i in ivs),
            "condition_meshes": len(cb.get("meshes", [])),
            "condition_ancestors": len(cb.get("ancestors", [])),
            "has_maximum_age": "maximumAge" in e,
            "has_gender_based": "genderBased" in e,
        })
    with open(h.OUT / "zetaris_expected.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    expected = {
        "endpoint": h.BASE + "/studies?" + urllib.parse.urlencode(PARAMS),
        "next_page_token_present": bool(page.get("nextPageToken")),
        "view_row_counts": {
            "ctgov_trial_core": len(rows),
            "ctgov_trial_conditions": sum(r["conditions"] for r in rows),
            "ctgov_trial_std_ages": sum(r["std_ages"] for r in rows),
            "ctgov_trial_phases": sum(r["phases"] for r in rows),
            "ctgov_trial_locations": sum(r["locations"] for r in rows),
            "ctgov_trial_interventions": sum(r["interventions"] for r in rows),
            "ctgov_trial_intervention_other_names": sum(r["intervention_other_names"] for r in rows),
            "ctgov_trial_condition_mesh": sum(r["condition_meshes"] for r in rows),
            "ctgov_trial_condition_ancestors": sum(r["condition_ancestors"] for r in rows),
        },
        "eligibility_len_max": max(r["eligibility_len"] for r in rows),
        "eligibility_len_sum": sum(r["eligibility_len"] for r in rows),
        "studies_with_maximum_age": sum(r["has_maximum_age"] for r in rows),
        "studies_with_gender_based": sum(r["has_gender_based"] for r in rows),
        "raw_page_bytes": len(json.dumps(page)),
    }
    (h.OUT / "zetaris_expected.json").write_text(json.dumps(expected, indent=2))
    print(json.dumps(expected, indent=2))


if __name__ == "__main__":
    main()
