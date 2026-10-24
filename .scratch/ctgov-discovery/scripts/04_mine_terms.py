"""Phase 4: what eligibility free text asks about → out/criteria_categories.csv, out/thresholds.csv, out/04_summary.json,
out/untagged_sample.json (input for the optional model pass).

Split rule follows the docstring of backend/app/trials/criteria.py.split_deterministic (not implemented yet):
'Inclusion Criteria:' / 'Exclusion Criteria:' headings (case-insensitive, optional 'Key'), bullets '* ', '- ', '1.', '•';
indented sub-bullets and wrapped lines merge into the parent item.
"""
from __future__ import annotations

import csv
import json
import random
import re
from collections import Counter, defaultdict

import ctgov_http as h

SAMPLES = ("A", "B", "C")

HEAD = re.compile(r"^\s*(?:#+\s*)?(?:\*\*)?\s*(key\s+|main\s+|major\s+)?(inclusion|exclusion)\s+criteria\b[^\n]*$", re.I | re.M)
BULLET = re.compile(r"^(\s*)(?:[*\-•]|\(?\d{1,2}\\?[.)]|[a-z]\\?[.)])\s+(.*)$")   # markdown escapes "1\\."

CATEGORIES: dict[str, str] = {
    "age_sex": r"\b(aged?|years? (?:of age|old)|≥\s*\d+\s*years|\bmale|female|women|men|sex|gender)\b",
    "diagnosis_histology": r"\b(histolog\w*|cytolog\w*|patholog\w*|confirmed (?:diagnosis|by)|diagnos\w+ (?:of|with))\b",
    "stage_grade_risk": r"\b(stage\s*(?:[IV]+|[0-4])[ABC]?|staging|grade\s*[1-4IV]|risk (?:group|stratum|category)|high[- ]risk|low[- ]risk|metasta\w+|advanced|locally advanced|unresectable)\b",
    "relapsed_refractory": r"\b(relaps\w*|refractory|recurr\w*|progress\w* (?:on|after|following)|resistant)\b",
    "biomarker_genetic": r"\b(EGFR|ALK|ROS-?1|KRAS|BRAF|MET(?:\s+exon)?|RET|NTRK|HER-?2|ERBB2|PD-?L1|MSI(?:-H)?|dMMR|MMR|TMB|MYCN|H3\s?K27M|fusion|rearrange\w+|mutation\w*|amplification|germline|BCR-?ABL|Philadelphia|FLT3|IDH[12]|NPM1|KMT2A|MLL|ETV6|biomarker|gene\w*|molecular|variant)\b",
    "performance_status": r"\b(ECOG|Karnofsky|Lansky|performance status|WHO PS|KPS)\b",
    "labs_organ_function": r"\b(ANC|neutrophil\w*|platelet\w*|ha?emoglobin|Hgb|Hb|bilirubin|ALT|AST|SGOT|SGPT|transaminase\w*|creatinine|eGFR|GFR|CrCl|creatinine clearance|INR|PT|aPTT|LVEF|ejection fraction|QTc\w*|albumin|ULN|organ function|bone marrow function|hepatic function|renal function|lab(?:oratory)? values?)\b",
    "measurable_disease": r"\b(RECIST|INRC|RANO|iRECIST|measurable|evaluable disease|target lesion\w*|Lugano|MRD|minimal residual)\b",
    "prior_treatment": r"\b(prior|previous\w*|previously|received|pretreated|treatment[- ]naive|naive|line\w* of (?:therapy|treatment)|chemotherap\w+|radiotherap\w+|radiation|surgery|resection|transplant\w*|HSCT|washout|within \d+ (?:days|weeks|months) (?:of|prior|before)|inhibitor|immunotherap\w+|checkpoint|anti-PD-?1|anti-PD-?L1|tyrosine kinase|TKI|monoclonal|investigational (?:agent|drug|product))\b",
    "cns_brain_mets": r"\b(CNS|central nervous system|brain metasta\w+|leptomeningeal|intracranial|carcinomatous meningitis|spinal cord compression)\b",
    "comorbidity_infection": r"\b(HIV|hepatitis|HBV|HCV|HBsAg|tuberculosis|TB|autoimmune|interstitial lung|pneumonitis|cardiac|heart failure|myocardial|arrhythmi\w+|angina|stroke|infection|second(?:ary)? (?:primary )?malignanc\w+|other malignanc\w+|prior malignanc\w+|another (?:primary )?(?:cancer|malignancy)|diabetes|hypertension|COVID|organ transplant)\b",
    "concomitant_meds": r"\b(CYP3A4?|CYP\d\w*|P-?gp|strong (?:inhibitor|inducer)\w*|steroid\w*|corticosteroid\w*|prednisone|dexamethasone|anticoagula\w+|warfarin|immunosuppress\w+|concomitant|live (?:attenuated )?vaccin\w+|vaccin\w+)\b",
    "pregnancy_contraception": r"\b(pregnan\w+|breast[- ]?feeding|lactat\w+|nursing|contracepti\w+|childbearing|WOCBP|sperm|abstinen\w+|menopaus\w+)\b",
    "consent_logistics": r"\b(consent|assent|life expectancy|comply|complian\w+|willing|able to (?:understand|swallow|attend)|travel|language|follow-?up visits|geographic\w*)\b",
}
CATS = {k: re.compile(v, re.I) for k, v in CATEGORIES.items()}

LAB_TERMS = r"(ANC|absolute neutrophil count|neutrophils?|platelets?|platelet count|ha?emoglobin|Hgb|Hb|total bilirubin|bilirubin|ALT|AST|SGOT|SGPT|serum creatinine|creatinine clearance|creatinine|CrCl|eGFR|GFR|INR|LVEF|ejection fraction|QTc\w*|albumin)"
CMP = r"(≥|≤|>=|<=|=<|=>|>|<|greater than or equal to|less than or equal to|greater than|less than|at least|no (?:more|greater) than|not exceeding|above|below|of\s+≥|of\s+≤)"
NUM = r"(\d+(?:[.,]\d+)?)"
UNIT = r"(\s*(?:[x×]\s*10\s*\^?\s*[0-9⁹⁰¹²³⁴⁵⁶⁷⁸]+\s*/\s*[LlµuμmM]+[Ll]?|[x×]\s*(?:the\s+)?(?:institutional\s+)?(?:upper limit of normal|ULN)|g/dL|g/L|mg/dL|µmol/L|μmol/L|umol/L|mmol/L|mL/min(?:/1\.73\s*m2|/1\.73\s*m²)?|/mm3|/mm³|/µL|/uL|/μL|cells/\w+|%|ms(?:ec)?\b|seconds|ULN))?"
LAB_RE = re.compile(r"\b" + LAB_TERMS + r"\b[^.;\n]{0,40}?" + CMP + r"\s*" + NUM + UNIT, re.I)
LAB_MENTION = re.compile(r"\b" + LAB_TERMS + r"\b", re.I)

# Age bounds only where an age word anchors the number (avoids "≥ 2 years before first dose").
_AGE_WORD = r"(?:\bage[ds]?\b|\byears? of age\b|\byears? old\b|\bolder\b)"
AGE_MIN = re.compile(r"\bage[ds]?\s*(?:of\s+)?(?:≥|>=|>|at\s+least|of\s+at\s+least|from)?\s*(\d{1,2}(?:\.\d)?)\s*(?:years|yrs|y)\b(?!\s*(?:before|prior|after|since|ago|or\s+(?:younger|less|under)))"
                     r"|(\d{1,2})\s*(?:years|yrs)(?:\s+of\s+age)?\s*(?:or|and)\s*(?:older|above|over)"
                     r"|\bage[ds]?\b[^.;\n]{0,15}?(\d{1,2})\s*(?:-|–|to)\s*\d{1,2}\s*years"
                     r"|\bage[ds]?\b[^.;\n]{0,15}?between\s+(\d{1,2})\s+and\s+\d{1,2}\s+years", re.I)
AGE_MAX_ONLY = re.compile(r"(?:under|younger than|less than|below|<|≤|up to)\s*(?:the\s+)?(?:age\s+of\s+)?\d{1,2}\s*years", re.I)
SEX_RESTRICT = re.compile(r"\b(?:female|women|male|men)\b", re.I)
PREG_CONTEXT = re.compile(r"pregnan|childbearing|contracept|sperm|lactat|breast-?feed|menopaus|WOCBP|fertile", re.I)


def split(text: str) -> tuple[list[tuple[str, str]], bool]:
    """→ ([(kind, item_text)], clean). clean = both headings found and each yields ≥1 item."""
    heads = list(HEAD.finditer(text))
    sections: list[tuple[str, str]] = []
    if heads:
        for i, m in enumerate(heads):
            end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
            sections.append((m.group(2).lower(), text[m.end():end]))
    else:
        sections.append(("unknown", text))
    items: list[tuple[str, str]] = []
    for kind, body in sections:
        cur: list[str] | None = None
        for line in body.splitlines():
            if not line.strip():
                continue
            b = BULLET.match(line)
            if b and len(b.group(1)) < 2:
                if cur:
                    items.append((kind, " ".join(cur)))
                cur = [b.group(2).strip()]
            elif cur is not None:
                cur.append((b.group(2) if b else line).strip())
            else:
                cur = [line.strip()]   # prose before the first bullet
        if cur:
            items.append((kind, " ".join(cur)))
    kinds = Counter(k for k, _ in items)
    clean = bool(heads) and kinds["inclusion"] > 0 and kinds["exclusion"] > 0
    return items, clean


def years(age: str | None) -> float | None:
    if not age:
        return None
    m = re.match(r"(\d+(?:\.\d+)?)\s*(Year|Month|Week|Day)", age)
    if not m:
        return None
    n, u = float(m.group(1)), m.group(2)
    return n if u == "Year" else n / {"Month": 12, "Week": 52.18, "Day": 365.25}[u]


def main() -> None:
    random.seed(20261023)
    summary: dict = {}
    cat_rows = []
    thr_rows = []
    untagged_sample = {}
    for key in SAMPLES:
        studies = json.loads((h.CACHE / f"sample_{key}.json").read_text())
        n = len(studies)
        study_hits: dict[str, set] = defaultdict(set)
        crit_hits = Counter()
        n_items = 0
        unclean = 0
        no_text = 0
        untagged: list[dict] = []
        lab_mentions = lab_with_num = lab_with_unit = 0
        age_text_studies = age_agree = age_disagree = age_no_structured = 0
        sex_mentions = 0
        sex_non_preg: list[str] = []
        disagreements = []
        unit_counts = Counter()
        for s in studies:
            nct = s["protocolSection"]["identificationModule"]["nctId"]
            elig = s["protocolSection"].get("eligibilityModule", {})
            text = elig.get("eligibilityCriteria") or ""
            if not text:
                no_text += 1
                continue
            items, clean = split(text)
            unclean += not clean
            n_items += len(items)
            for kind, item in items:
                tags = [c for c, rx in CATS.items() if rx.search(item)]
                for t in tags:
                    study_hits[t].add(nct)
                    crit_hits[t] += 1
                if not tags:
                    untagged.append({"nct": nct, "kind": kind, "text": item[:400]})
                for m in LAB_MENTION.finditer(item):
                    lab_mentions += 1
                for m in LAB_RE.finditer(item):
                    lab_with_num += 1
                    unit = (m.group(4) or "").strip()
                    if unit or m.group(1).upper() == "INR":   # INR is a unitless ratio
                        lab_with_unit += 1
                        unit_counts[re.sub(r"\s+", "", unit.lower())[:20]] += 1
                    if len(thr_rows) < 4000:
                        thr_rows.append({"sample": key, "nct": nct, "lab": m.group(1), "comparator": m.group(2), "value": m.group(3),
                                         "unit": unit, "as_written": m.group(0)[:120]})
            # age: structured vs free text (min age only; inclusion-side criteria that name an age)
            smin = years(elig.get("minimumAge"))
            text_ages = []
            for kind, item in items:
                if kind == "exclusion":
                    continue
                for m in AGE_MIN.finditer(item):
                    window = item[max(0, m.start() - 25):m.end()]
                    if AGE_MAX_ONLY.search(window):
                        continue
                    text_ages.append(float(next(g for g in m.groups() if g)))
            if text_ages:
                age_text_studies += 1
                tmin = min(text_ages)
                if smin is None:
                    age_no_structured += 1
                elif abs(tmin - smin) < 1:
                    age_agree += 1
                else:
                    age_disagree += 1
                    disagreements.append(f"{nct}: structured min {elig.get('minimumAge')}, text min {tmin:g} y")
            # sex: free-text mentions outside pregnancy/contraception context
            for kind, item in items:
                if SEX_RESTRICT.search(item):
                    sex_mentions += 1
                    if not PREG_CONTEXT.search(item):
                        sex_non_preg.append(f"{nct} [{elig.get('sex')}]: {item[:140]}")
        summary[key] = {
            "studies": n,
            "studies_without_eligibility_text": no_text,
            "studies_not_split_cleanly": unclean,
            "criteria_items": n_items,
            "criteria_per_study_mean": round(n_items / max(1, n - no_text), 1),
            "untagged_criteria": len(untagged),
            "category_share_of_studies": {c: round(len(study_hits[c]) / n, 3) for c in CATEGORIES},
            "category_criteria_count": {c: crit_hits[c] for c in CATEGORIES},
            "lab_mentions": lab_mentions,
            "lab_thresholds_numeric": lab_with_num,
            "lab_thresholds_with_unit": lab_with_unit,
            "lab_threshold_units_top": unit_counts.most_common(12),
            "age_in_text_studies": age_text_studies,
            "age_text_agrees_with_structured_min": age_agree,
            "age_text_disagrees": age_disagree,
            "age_disagreement_examples": disagreements[:8],
            "age_in_text_no_structured_min": age_no_structured,
            "structured_sex_restricted": sum(1 for s in studies if s["protocolSection"].get("eligibilityModule", {}).get("sex") in ("FEMALE", "MALE")),
            "criteria_mentioning_sex": sex_mentions,
            "criteria_mentioning_sex_outside_pregnancy_context": len(sex_non_preg),
            "sex_outside_pregnancy_examples": sex_non_preg[:6],
        }
        for c in CATEGORIES:
            cat_rows.append({"sample": key, "category": c, "share_of_studies": summary[key]["category_share_of_studies"][c],
                             "criteria_tagged": crit_hits[c]})
        untagged_sample[key] = random.sample(untagged, min(50, len(untagged)))

    with open(h.OUT / "criteria_categories.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(cat_rows[0]))
        w.writeheader()
        w.writerows(cat_rows)
    with open(h.OUT / "thresholds.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(thr_rows[0]))
        w.writeheader()
        w.writerows(thr_rows)
    (h.OUT / "untagged_sample.json").write_text(json.dumps(untagged_sample, indent=1))
    (h.OUT / "04_summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
