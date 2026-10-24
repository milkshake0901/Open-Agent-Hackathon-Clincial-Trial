"""Check the recommended `fields=` list for ctgov.fetch against the live API and measure the payload saving → out/06_fields.json."""
from __future__ import annotations

import json

import ctgov_http as h

FIELDS = [
    "NCTId", "BriefTitle", "OverallStatus", "StudyType", "Phase", "LastUpdatePostDate",
    "Condition", "Keyword", "ConditionMeshId", "ConditionMeshTerm", "ConditionAncestorTerm",
    "EligibilityCriteria", "Sex", "MinimumAge", "MaximumAge", "StdAge", "HealthyVolunteers",
    "InterventionType", "InterventionName", "InterventionOtherName", "InterventionMeshTerm",
    "LocationFacility", "LocationCity", "LocationState", "LocationCountry", "LocationStatus", "LocationGeoPoint",
    "CentralContactName", "CentralContactEMail", "CentralContactPhone",
]
BASE_PARAMS = {
    "query.cond": "non-small cell lung cancer",
    "filter.overallStatus": "RECRUITING|NOT_YET_RECRUITING",
    "filter.geo": "distance(-33.8688,151.2093,50km)",
    "pageSize": 100,
}


def main() -> None:
    full = h.get("/studies", BASE_PARAMS)
    slim = h.get("/studies", {**BASE_PARAMS, "fields": "|".join(FIELDS)})
    s0 = slim["studies"][0]
    out = {
        "fields": FIELDS,
        "studies_full": len(full["studies"]),
        "studies_slim": len(slim["studies"]),
        "bytes_full": len(json.dumps(full)),
        "bytes_slim": len(json.dumps(slim)),
        "slim_top_level_keys": sorted(s0),
        "slim_protocol_modules": sorted(s0.get("protocolSection", {})),
        "slim_has_geoPoint": "geoPoint" in (s0["protocolSection"].get("contactsLocationsModule", {}).get("locations") or [{}])[0],
    }
    out["saving"] = round(1 - out["bytes_slim"] / out["bytes_full"], 3)
    (h.OUT / "06_fields.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
