"""Phase 2: fetch the three trial samples (full records, no `fields` filter) → cache + out/samples.json (counts, queries).

Sample studies are written to cache/sample_<X>.json so later phases read one file per sample.
"""
from __future__ import annotations

import json

import ctgov_http as h

SYDNEY = "distance(-33.8688,151.2093,50km)"   # Sydney CBD, 50 km radius

SAMPLES = {
    "A": {
        "label": "target: NSCLC, recruiting / not yet recruiting, within 50 km of Sydney",
        "params": {
            "query.cond": "non-small cell lung cancer",
            "filter.overallStatus": "RECRUITING|NOT_YET_RECRUITING",
            "filter.geo": SYDNEY,
        },
        "cap": 2000,
    },
    "B": {
        "label": "paediatric oncology: neuroblastoma/medulloblastoma/leukemia, StdAge CHILD, recruiting",
        "params": {
            "query.cond": "neuroblastoma OR medulloblastoma OR leukemia",
            "query.term": "AREA[StdAge]CHILD",
            "filter.overallStatus": "RECRUITING",
        },
        "cap": 2000,
    },
    "C": {
        "label": "control: recruiting interventional, no condition filter, most recently updated first",
        "params": {
            "query.term": "AREA[StudyType]INTERVENTIONAL",
            "filter.overallStatus": "RECRUITING",
            "sort": "LastUpdatePostDate:desc",
        },
        "cap": 500,
    },
}


def main() -> None:
    out = {}
    for key, s in SAMPLES.items():
        first = h.get("/studies", {**s["params"], "pageSize": 1, "countTotal": "true"})
        total = first.get("totalCount")
        page_size = min(1000, s["cap"])
        studies = h.get_all("/studies", {**s["params"], "pageSize": page_size}, s["cap"])
        (h.CACHE / f"sample_{key}.json").write_text(json.dumps(studies))
        out[key] = {"label": s["label"], "params": s["params"], "total_matching": total, "fetched": len(studies), "cap": s["cap"]}
        print(key, out[key])
    out["live_calls_this_run"] = h.live_calls
    (h.OUT / "samples.json").write_text(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
