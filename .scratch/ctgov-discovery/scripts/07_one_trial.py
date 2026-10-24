"""Extract one Trial: structured eligibility fields, Criteria split, topic tags and lab / ECOG thresholds
→ stdout and out/one_trial_<NCT>.json. Uses the same split rule and keyword dictionary as 04_mine_terms.py,
so its tags are exactly what the coverage figures counted (including the EGFR/eGFR false positive).

Usage: python3 07_one_trial.py NCT07680790
"""
from __future__ import annotations

import html
import importlib.util
import json
import re
import sys
from pathlib import Path

import ctgov_http as h

_spec = importlib.util.spec_from_file_location("mine", Path(__file__).with_name("04_mine_terms.py"))
mine = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mine)

ECOG = re.compile(r"\bECOG\b[^.;\n]{0,40}?(\d)\s*(?:-|–|to|or)\s*(\d)|\bECOG\b[^.;\n]{0,40}?(?:≤|<=|of)\s*(\d)", re.I)


def clean(s: str) -> str:
    """Undo the API's markdown escapes (\\&gt; → >, 1\\. → 1.)."""
    return html.unescape(s.replace("\\", ""))


def main(nct: str) -> None:
    study = h.get(f"/studies/{nct}")
    ps = study["protocolSection"]
    elig = ps.get("eligibilityModule", {})
    items, split_clean = mine.split(elig.get("eligibilityCriteria") or "")

    criteria = []
    for ordinal, (kind, raw) in enumerate(items, 1):
        text = clean(raw)
        labs = [{"lab": m.group(1), "cmp": m.group(2), "value": m.group(3), "unit": (m.group(4) or "").strip() or None}
                for m in mine.LAB_RE.finditer(text)]
        ecog = ECOG.search(text)
        criteria.append({
            "id": f"{nct}:{ordinal}",
            "kind": kind,
            "text": text,
            "topics": [c for c, rx in mine.CATS.items() if rx.search(text)],
            "lab_thresholds": labs,
            "ecog_max": int(ecog.group(2) or ecog.group(3)) if ecog else None,
        })

    out = {
        "nct_id": nct,
        "title": ps["identificationModule"]["briefTitle"],
        "status": ps["statusModule"]["overallStatus"],
        "conditions": ps.get("conditionsModule", {}).get("conditions", []),
        "condition_mesh": [m["term"] for m in study.get("derivedSection", {}).get("conditionBrowseModule", {}).get("meshes", [])],
        "min_age_years": mine.years(elig.get("minimumAge")),
        "max_age_years": mine.years(elig.get("maximumAge")),
        "sex": elig.get("sex"),
        "split_clean": split_clean,
        "criteria": criteria,
    }
    path = h.OUT / f"one_trial_{nct}.json"
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False))

    print(f"{nct}  {out['title']}\n{out['status']} · {', '.join(out['conditions'])}")
    print(f"MeSH: {', '.join(out['condition_mesh']) or '-'}")
    print(f"Age {out['min_age_years']}–{out['max_age_years'] or 'no max'} · sex {out['sex']} · split clean: {split_clean}\n")
    for c in criteria:
        print(f"[{c['kind'][:3]}] {c['id']}  topics={c['topics'] or '-'}")
        print(f"      {c['text']}")
        for t in c["lab_thresholds"]:
            print(f"      lab: {t['lab']} {t['cmp']} {t['value']} {t['unit'] or '(no unit)'}")
        if c["ecog_max"] is not None:
            print(f"      ECOG ≤ {c['ecog_max']}")
    print(f"\n→ {path}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "NCT07680790")
