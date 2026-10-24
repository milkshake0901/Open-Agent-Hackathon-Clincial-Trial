"""Phase 3: structured field coverage per sample → out/coverage_<X>.csv, out/registry_enum_stats.csv, out/03_summary.json.

present = share of studies where the leaf has at least one non-empty value.
For list paths, list_len_* is the number of leaf values per study (among studies where present).
"""
from __future__ import annotations

import csv
import json
import statistics
from collections import Counter

import ctgov_http as h

SAMPLES = ("A", "B", "C")

# Bucket rules: (bucket, path prefixes). A field can match several buckets.
BUCKETS = [
    ("demographics", ["protocolSection.eligibilityModule.sex", "protocolSection.eligibilityModule.minimumAge",
                      "protocolSection.eligibilityModule.maximumAge", "protocolSection.eligibilityModule.stdAges",
                      "protocolSection.eligibilityModule.healthyVolunteers", "protocolSection.eligibilityModule.gender"]),
    ("diagnosis", ["protocolSection.conditionsModule", "derivedSection.conditionBrowseModule"]),
    ("treatment_history", ["protocolSection.armsInterventionsModule.interventions", "derivedSection.interventionBrowseModule"]),
    ("location_access", ["protocolSection.contactsLocationsModule"]),
    ("trial_filter", ["protocolSection.statusModule", "protocolSection.designModule", "protocolSection.identificationModule.nctId",
                      "protocolSection.identificationModule.briefTitle", "protocolSection.sponsorCollaboratorsModule.leadSponsor"]),
    ("free_text", ["protocolSection.eligibilityModule.eligibilityCriteria", "protocolSection.eligibilityModule.studyPopulation",
                   "protocolSection.descriptionModule", "protocolSection.eligibilityModule.genderDescription"]),
]
NOT_USEFUL_WHY = {
    "resultsSection": "posted results; describes past participants, not who can enrol",
    "documentSection": "protocol/SAP document links; no per-patient value",
    "annotationSection": "registry QC and unposted events",
    "hasResults": "results flag",
    "protocolSection.outcomesModule": "trial endpoints, not entry requirements",
    "protocolSection.referencesModule": "citations and links",
    "protocolSection.oversightModule": "regulatory flags",
    "protocolSection.ipdSharingStatementModule": "data sharing plan",
    "protocolSection.sponsorCollaboratorsModule": "sponsor details (lead sponsor kept as a trial filter)",
    "protocolSection.identificationModule": "ids and titles (nctId/briefTitle kept as trial filters)",
    "protocolSection.armsInterventionsModule.armGroups": "arm descriptions; useful for UI, not for eligibility",
    "derivedSection.miscInfoModule": "registry versioning",
    "derivedSection": "derived browse data",
    "protocolSection.eligibilityModule.samplingMethod": "observational sampling design",
}


def values_at(node, parts: list[str]) -> list:
    if not parts:
        return [node]
    head, rest = parts[0], parts[1:]
    is_list = head.endswith("[]")
    key = head.removesuffix("[]")
    if not isinstance(node, dict) or key not in node:
        return []
    child = node[key]
    if is_list:
        out = []
        for item in child if isinstance(child, list) else [child]:
            out.extend(values_at(item, rest))
        return out
    return values_at(child, rest)


def non_empty(v) -> bool:
    return v not in (None, "", [], {})


def buckets_for(path: str) -> list[str]:
    bare = path.replace("[]", "")
    hit = [b for b, prefixes in BUCKETS if any(bare.startswith(p) for p in prefixes)]
    return hit or ["not_useful"]


def why_not_useful(path: str) -> str:
    bare = path.replace("[]", "")
    best = max((p for p in NOT_USEFUL_WHY if bare.startswith(p)), key=len, default=None)
    return NOT_USEFUL_WHY.get(best, "no patient-side counterpart")


def short(v) -> str:
    return json.dumps(v, sort_keys=True) if isinstance(v, (dict, list)) else str(v)


def main() -> None:
    catalog = list(csv.DictReader(open(h.OUT / "field_catalog.csv")))
    summary = {}
    for key in SAMPLES:
        studies = json.loads((h.CACHE / f"sample_{key}.json").read_text())
        n = len(studies)
        rows = []
        for f in catalog:
            parts = f["path"].split(".")
            per_study = [[v for v in values_at(s, parts) if non_empty(v)] for s in studies]
            present = [vs for vs in per_study if vs]
            flat = [short(v) for vs in present for v in vs]
            counts = Counter(flat)
            is_enumish = bool(f["enum_values"]) or f["type"].startswith("BOOLEAN") or (flat and max(map(len, flat)) <= 60)
            lens = [len(vs) for vs in present]
            rows.append({
                "path": f["path"],
                "piece_name": f["piece_name"],
                "buckets": "|".join(buckets_for(f["path"])),
                "present_share": round(len(present) / n, 3) if n else 0,
                "distinct_values": len(counts),
                "top_values": " ; ".join(f"{v[:60]} ({c})" for v, c in counts.most_common(10)) if is_enumish else "",
                "list_len_median": statistics.median(lens) if f["is_list"] == "True" and lens else "",
                "list_len_max": max(lens) if f["is_list"] == "True" and lens else "",
                "not_useful_reason": why_not_useful(f["path"]) if buckets_for(f["path"]) == ["not_useful"] else "",
            })
        with open(h.OUT / f"coverage_{key}.csv", "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        summary[key] = {"n": n, "fields_present_any": sum(1 for r in rows if r["present_share"] > 0)}

    # Registry-wide distributions for the enum fields we care about, and list sizes.
    enum_pieces = ["Sex", "StdAge", "HealthyVolunteers", "OverallStatus", "Phase", "StudyType", "InterventionType", "LocationStatus", "GenderBased"]
    reg_rows = []
    for piece in enum_pieces:
        for st in h.get("/stats/field/values", {"fields": piece}):
            tv = st.get("topValues") or []
            for v in tv:
                reg_rows.append({"piece": piece, "field": st.get("field"), "value": v.get("value"), "studies": v.get("studiesCount"),
                                 "missing_studies": st.get("missingStudiesCount")})
            if st.get("type") == "BOOLEAN":
                for k in ("trueCount", "falseCount"):
                    reg_rows.append({"piece": piece, "field": st.get("field"), "value": k, "studies": st.get(k), "missing_studies": st.get("missingStudiesCount")})
    # One call per piece: the API 404s the whole request if any piece has no list-size stats.
    size_pieces = ["Condition", "Keyword", "StdAge", "Phase", "Location", "Intervention", "InterventionName", "ConditionMesh", "ConditionMeshTerm"]
    size_refused = []
    for piece in size_pieces:
        try:
            stats = h.get("/stats/field/sizes", {"fields": piece})
        except RuntimeError as e:
            size_refused.append(f"{piece}: {str(e)[:160]}")
            continue
        for st in stats:
            top = ", ".join(f"{t['size']}:{t['studiesCount']}" for t in (st.get("topSizes") or [])[:5])
            reg_rows.append({"piece": st.get("piece"), "field": st.get("field"), "value": f"list size min {st.get('minSize')} max {st.get('maxSize')}; top {top}",
                             "studies": "", "missing_studies": st.get("missingStudiesCount")})
    summary["sizes_refused"] = size_refused
    with open(h.OUT / "registry_enum_stats.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["piece", "field", "value", "studies", "missing_studies"])
        w.writeheader()
        w.writerows(reg_rows)
    summary["live_calls_this_run"] = h.live_calls
    (h.OUT / "03_summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
