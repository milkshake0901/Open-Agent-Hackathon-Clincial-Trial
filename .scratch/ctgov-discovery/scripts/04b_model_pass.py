"""Phase 4 step 3 (optional model pass): tally the model's variable labels for 50 random untagged Criteria per sample.

Input: out/untagged_sample.json (from 04_mine_terms.py) and out/model_pass_labels.json (model-derived, one label per item, same order).
Output: out/model_pass_categories.csv. A category is "new" if it is not a dictionary category and appears >= 3 times overall.
"""
from __future__ import annotations

import csv
import json
from collections import Counter

import ctgov_http as h

DICTIONARY_GAPS = {   # labels that are dictionary categories the regexes missed (wording gaps), not new categories
    "other_malignancy": "comorbidity_infection", "comorbidity_other": "comorbidity_infection", "bleeding_thrombosis": "comorbidity_infection",
    "biomarker_other": "biomarker_genetic", "prior_treatment_other": "prior_treatment", "concomitant_meds_other": "concomitant_meds",
    "pregnancy_contraception": "pregnancy_contraception", "logistics_compliance": "consent_logistics", "age_sex": "age_sex",
    "diagnosis_subtype": "diagnosis_histology", "disease_status": "relapsed_refractory", "labs_other": "labs_organ_function",
}
NOT_CATEGORIES = {"other": "unclassified", "noise_heading": "splitter artifact (heading or stray line, not a Criterion)"}


def main() -> None:
    items = json.loads((h.OUT / "untagged_sample.json").read_text())
    labels = json.loads((h.OUT / "model_pass_labels.json").read_text())["labels"]
    per = {k: Counter(labels[k]) for k in labels}
    total = sum(per.values(), Counter())
    rows = []
    for cat, n in total.most_common():
        rows.append({"label": cat, "A": per["A"][cat], "B": per["B"][cat], "C": per["C"][cat], "total": n,
                     "kind": NOT_CATEGORIES.get(cat) or (f"dictionary gap → {DICTIONARY_GAPS[cat]}" if cat in DICTIONARY_GAPS else ("new category" if n >= 3 else "rare")),
                     "example": next(items[k][i]["text"][:120] for k in labels for i, l in enumerate(labels[k]) if l == cat)})
    with open(h.OUT / "model_pass_categories.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    for r in rows:
        print(f"{r['label']:24s} A={r['A']:<3} B={r['B']:<3} C={r['C']:<3} total={r['total']:<3} {r['kind']}")


if __name__ == "__main__":
    main()
