"""Phase 1: full field catalog from /studies/metadata, /studies/enums and /studies/search-areas → out/field_catalog.csv.

One row per leaf field. `path` is dotted from the study root; a list hop is shown as `[]` (e.g. ...locations[].city).
`searchable_by` lists the query params / AREA names whose search areas include the field's piece.
"""
from __future__ import annotations

import csv
import json

import ctgov_http as h


def main() -> None:
    version = h.get("/version")
    size = h.get("/stats/size")
    meta = h.get("/studies/metadata")
    enums = {e["type"]: [v["value"] for v in e["values"]] for e in h.get("/studies/enums")}
    areas = h.get("/studies/search-areas")

    searchable: dict[str, list[str]] = {}
    for doc in areas:
        for area in doc["areas"]:
            label = f"query.{area['param']}" if area.get("param") else f"AREA[{area['name']}]"
            for part in area["parts"]:
                for piece in part["pieces"]:
                    searchable.setdefault(piece, [])
                    if label not in searchable[piece]:
                        searchable[piece].append(label)

    rows = []

    def walk(node: dict, prefix: str) -> None:
        is_list = node.get("type", "").endswith("[]")
        path = f"{prefix}.{node['name']}" if prefix else node["name"]
        if is_list:
            path += "[]"
        kids = node.get("children") or []
        if kids:
            for c in kids:
                walk(c, path)
            return
        t = node.get("type", "").removesuffix("[]")
        rows.append({
            "path": path,
            "piece_name": node.get("piece", ""),
            "type": node.get("sourceType", "") + (f"/{t}" if t and t.lower() != node.get("sourceType", "").lower() else ""),
            "is_list": "[]" in path,
            "enum_values": "|".join(enums.get(t, [])) if node.get("isEnum") else "",
            "description": (node.get("description") or node.get("title") or "").replace("\n", " "),
            "searchable_by": " ".join(searchable.get(node.get("piece", ""), [])),
        })

    for n in meta:
        walk(n, "")

    h.OUT.mkdir(exist_ok=True)
    with open(h.OUT / "field_catalog.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    summary = {
        "api_version": version["apiVersion"],
        "data_timestamp": version["dataTimestamp"],
        "total_studies": size["totalStudies"],
        "leaf_fields": len(rows),
        "leaf_fields_by_section": {},
        "enum_types": len(enums),
        "searchable_leaf_fields": sum(1 for r in rows if r["searchable_by"]),
        "search_areas": [(a["name"], a.get("param")) for d in areas for a in d["areas"]],
    }
    for r in rows:
        sec = r["path"].split(".")[0]
        summary["leaf_fields_by_section"][sec] = summary["leaf_fields_by_section"].get(sec, 0) + 1
    (h.OUT / "01_summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
