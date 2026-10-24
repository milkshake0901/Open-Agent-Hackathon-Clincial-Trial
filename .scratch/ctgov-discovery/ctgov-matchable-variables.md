# ClinicalTrials.gov: what we can match a patient on

Executes `docs/plans/ctgov-field-discovery.md`. Everything lives in `.scratch/ctgov-discovery/`, which git ignores. Each number below comes from a script in `scripts/` that re-runs from `cache/` without calling the API. The output file is named next to each number.

## 1. Summary

- **Only age, sex and site location are structured and checkable today.** `minimumAge` is filled for 100% / 75% / 98% of studies (samples A / B / C), and `sex` and `stdAges` for 100%. Site `geoPoint` and per-site `status` are filled for at least 99% of studies. All three can be checked without a model, but **our Facts can't hold any of them**: there's no date of birth, sex or patient location.
- **Diagnosis is structured, but too coarse for oncology matching.** `conditions` is 100% filled and MeSH terms are 96% / 93% / 82% filled. Histology, stage, line of therapy and relapse status exist only in free text.
- **Most of what a trial asks about is free text.** Mean of 18.7 / 15.8 / 17.1 Criteria per study. In the NSCLC target sample, the share of trials mentioning each topic is: prior treatment 97%, stage or extent 98%, biomarkers 90%, comorbidities 84%, labs 78%, performance status 78%, CNS metastases 76% and measurable disease 75%.
- **Lab thresholds can be checked deterministically in about half of mentions**: 35% / 49% / 51% of lab mentions have a number and a unit. Many thresholds are "× ULN", which needs the lab's reference range, and **`fact` has no reference-range column**.
- **`filter.geo` isn't enough on its own.** It keeps a Trial if *any* site is within range. In 11 of 96 NSCLC Trials near Sydney, none of the Sydney sites is recruiting.
- **The `trial` table drops nearly everything structured.** Age bounds, sex, phases, MeSH terms, interventions and sites are all fetched and then thrown away.
- **Zetaris was not tested.** The session had no API key. `scripts/05_zetaris_probe.sql` is ready to run, and the expected value for every check is precomputed. The page it registers is **4.0 MB** of JSON (2.5 MB with the recommended `fields=`), so payload size is the first risk to check.

## 2. Run details

| | |
|---|---|
| API version | 2.0.5, data timestamp 2026-10-22T09:00:04 (`out/01_summary.json`) |
| Registry size | 608,228 studies; 342 leaf fields, 66 searchable through `query.*` / `AREA[]` |
| Run date | 2026-10-23 |
| Live API calls | 29 cached responses (`cache/`, 59 MB), spaced at least 1.3 s apart; no 429s |
| Zetaris | 2.4.3.1-hackathon containers running locally; **not queried** (no API key) |
| Model pass | Labels by Claude Opus 5.5 in-session, reading public trial text only (`out/model_pass_labels.json`) |

| Sample | Query | Matching | Fetched |
|---|---|---|---|
| A (target) | `query.cond=non-small cell lung cancer`, `filter.overallStatus=RECRUITING\|NOT_YET_RECRUITING`, `filter.geo=distance(-33.8688,151.2093,50km)` | 96 | 96 |
| B (paediatric oncology) | `query.cond=neuroblastoma OR medulloblastoma OR leukemia`, `query.term=AREA[StdAge]CHILD`, `filter.overallStatus=RECRUITING` | 608 | 608 |
| C (control) | `query.term=AREA[StudyType]INTERVENTIONAL`, `filter.overallStatus=RECRUITING`, `sort=LastUpdatePostDate:desc` | 47,419 | 500 |

## 3. Matchable variables

Coverage is the share of studies in samples A / B / C. For structured fields, that means the field is present and non-empty. For free text, it means the dictionary tagged at least one Criterion in that category. Sources: `out/coverage_*.csv`, `out/04_summary.json`, `out/03b_sites.json`.

"Zetaris OK?" is **not run** throughout (see section 6). The view that would carry each field is named.

| variable | source | coverage A / B / C | patient Fact resource | deterministic check? | Zetaris OK? | notes |
|---|---|---|---|---|---|---|
| Age | `eligibilityModule.minimumAge`, `maximumAge`, `stdAges` | min 100/75/98%, max 3/75/49%, stdAges 100% | **none: gap** (date of birth) | Yes | not run (`ctgov_trial_core`, `_std_ages`) | Strings like "18 Years", "36 Months", "1 Day" need normalising. A missing max means no limit. Free-text ages that differ from the structured min are mostly conditional (they pick the performance scale, cohort or creatinine cut-off), not stricter limits. |
| Sex | `eligibilityModule.sex` | 100/100/100% (FEMALE/MALE in 0/1/41 studies) | **none: gap** | Yes | not run (`ctgov_trial_core`) | 8/112/89 free-text mentions fall outside pregnancy wording. Most say "male or female". |
| Healthy volunteer | `eligibilityModule.healthyVolunteers` | 100/98/100% | n/a (a patient is never a healthy volunteer) | Yes | not run | A trial filter, not a patient check. |
| Distance to a recruiting site | `contactsLocationsModule.locations[].geoPoint` + `.status` | 100/100/100%; 96/99/99% of sites have geoPoint | **none: gap** (patient location) | Yes | not run (`ctgov_trial_locations`, plus a haversine query) | Median 65 sites per A trial. 85/96 A trials have a recruiting site within 50 km. |
| Primary diagnosis | `conditionsModule.conditions`, `derivedSection.conditionBrowseModule.meshes/ancestors` | conditions 100%; MeSH 96/93/82%; ancestors 95/93/80% | Condition | Partly: MeSH ancestor match if Conditions are coded | not run (`ctgov_trial_conditions`, `_condition_mesh`, `_ancestors`) | `conditions` is free-typed by sponsors. Use MeSH for matching and `conditions` for display. |
| Histology / diagnosis confirmation | free text: diagnosis_histology | 85/59/56% | Condition | No (model) | via `eligibility_text` | |
| Stage, grade, risk group, extent | free text: stage_grade_risk | 98/41/36% | Condition (or Observation for TNM) | Partly (TNM / "stage IV" keywords) | via `eligibility_text` | |
| Relapsed / refractory / progression | free text: relapsed_refractory | 58/55/24% | Condition + dated Procedure/MedicationStatement | No (model plus timeline) | via `eligibility_text` | Also covers "no progression after CCRT" (model pass). |
| Biomarkers and genetics | free text: biomarker_genetic | 90/48/34% | Observation (subject = gene/marker) | Yes, if the Observation is coded; otherwise model | via `eligibility_text` | Model pass adds CD19/CD123 expression and "no actionable alterations". |
| Performance status | free text: performance_status | 78/54/24% | Observation | Yes (scale + threshold) | via `eligibility_text` | Karnofsky, Lansky or ECOG is often chosen by age. |
| Labs and organ function | free text: labs_organ_function | 78/60/42% | Observation | Partly: 35/49/51% of mentions have a number and unit | via `eligibility_text` | Many "× ULN" thresholds need the reference range (**gap**). Text is markdown-escaped (`\<`, `\>`). |
| Measurable disease | free text: measurable_disease | 75/26/17% | Observation / Procedure (imaging) | No (model) | via `eligibility_text` | RECIST, INRC, RANO, MRD |
| Prior treatment and washout | free text: prior_treatment; `interventions[]`, `interventionBrowseModule` | text 97/84/78%; interventions 100/90/100% | MedicationStatement, Procedure | Partly: drug names yes, lines of therapy and windows need dates plus a model | via `eligibility_text`; `ctgov_trial_interventions`, `_other_names` | `otherNames` (53/33/35%) and intervention MeSH (70/55/50%) give synonyms. |
| CNS / brain metastases | free text: cns_brain_mets | 76/41/23% | Condition | Partly (presence yes; "active vs treated and stable" is model) | via `eligibility_text` | |
| Comorbidities and infections | free text: comorbidity_infection | 84/66/67% | Condition, Observation (serology) | No (model) | via `eligibility_text` | Dictionary misses wordings like "additional malignancy", "infections" and "cardiovascular" (model pass). |
| Current medications | free text: concomitant_meds | 74/44/42% | MedicationStatement | Partly: named drugs yes, CYP3A4 class needs an interaction knowledge base | via `eligibility_text` | |
| Pregnancy and contraception | free text: pregnancy_contraception | 36/60/60% | Observation (pregnancy test) | Mostly not a matching question | via `eligibility_text` | Settled at screening. Better as a Doctor question than an exclusion. |
| Consent, life expectancy, logistics | free text: consent_logistics | 60/79/68% | **none: gap** (patient attributes, clinician judgement) | No | via `eligibility_text` | |
| Drug hypersensitivity *(model-derived)* | model pass: 8 / 2 / 2 of 50 untagged | n/a | **none: gap** (no allergy resource) | Yes, if allergies were recorded | via `eligibility_text` | Almost always about the study drug, which a patient won't have had. |
| Oral intake / GI absorption *(model-derived)* | model pass: 6 / 1 / 1 of 50 | n/a | Condition, Procedure (gastrectomy) | No | via `eligibility_text` | |
| Investigator judgement *(model-derived)* | model pass: 5 / 3 / 6 of 50 | n/a | n/a | Never | via `eligibility_text` | Always unknown, so always a Doctor question. |
| Psychiatric / substance use *(model-derived)* | model pass: 0 / 0 / 6 of 50 | n/a | Condition | No | via `eligibility_text` | Matters only outside oncology. |
| Body or tumour size *(model-derived)* | model pass: 0 / 1 / 4 of 50 | n/a | Observation | Yes (weight); partly (lesion size) | via `eligibility_text` | |
| Other trial participation *(model-derived)* | model pass: 1 / 1 / 1 of 50 | n/a | **none: gap** | No | via `eligibility_text` | |
| Effusions *(model-derived)* | model pass: 3 / 0 / 0 of 50 | n/a | Condition | No | via `eligibility_text` | |

Field buckets for all 342 leaf fields are in `out/coverage_*.csv` (column `buckets`): demographics 7, diagnosis 12, treatment history 15, location and access 20, trial filters 56, free text 5, and 228 not useful for matching. Each not-useful row has a one-line reason (mostly `resultsSection`, document links, outcomes and registry admin).

## 4. Structured fields we don't store today

`trial` keeps `nct_id`, `title`, `conditions`, `status` and `eligibility_text`. These are proposed columns only. The schema has not been changed.

| Field | Proposed storage | Why |
|---|---|---|
| `minimumAge`, `maximumAge` | `min_age_years numeric NULL`, `max_age_years numeric NULL` (normalised from "N Years/Months/Weeks/Days"; NULL means no limit) | Deterministic age gate |
| `sex` | `sex text CHECK (sex IN ('ALL','FEMALE','MALE'))` | Deterministic gate |
| `stdAges` | `std_ages text[]` | Cheap pre-filter; derived from min/max |
| `healthyVolunteers` | `healthy_volunteers boolean` | Trial filter |
| `phases` | `phases text[]` | UI and filtering |
| `conditionBrowseModule.meshes[].id/term`, `ancestors[].term` | `condition_mesh_ids text[]`, `condition_mesh_terms text[]`, `condition_ancestor_terms text[]` | Diagnosis matching on a controlled vocabulary |
| `interventions[]` (`type`, `name`, `otherNames`), `interventionBrowseModule.meshes[].term` | new `trial_intervention (nct_id, type, name, other_names text[], mesh_terms text[])` | Prior or current drug overlap; UI |
| `locations[]` (`facility`, `city`, `country`, `status`, `geoPoint`) | new `trial_site (nct_id, facility, city, country, status, lat, lon)` | Distance to the nearest *recruiting* site |
| `keywords` | `keywords text[]` | Search and display |
| `lastUpdatePostDate` | `last_update_posted date` | Cheap check for "did this change?" before re-hashing |
| `centralContacts[]` | `trial_contact` or JSON | UI: who to call |

## 5. Gaps in our patient model

`fact.resource` allows `Condition`, `Observation`, `MedicationStatement` and `Procedure`. Trials ask about the following, which have no place to live:

| Variable | Asked by | Fact or patient attribute? |
|---|---|---|
| Age / date of birth | 100% of trials (structured) | **Patient attribute.** De-identification removes date of birth, so store a coarse value such as birth year or age in years at the Profile version. An "age" Fact would go stale. |
| Sex | 100% (structured) | **Patient attribute.** |
| Location | Every distance check | **Patient attribute**, kept coarse (postcode or suburb centroid). De-identification removes addresses. |
| Lab reference range (for "× ULN") | A large share of lab thresholds (`out/04_summary.json`, `lab_threshold_units_top`) | **Fact columns**: add `ref_low` and `ref_high` to Observation Facts, taken from the same report line. |
| Allergies / hypersensitivity | Model pass: 12 of 150 untagged Criteria | A new `AllergyIntolerance` resource value, or Condition with an agreed subject convention. |
| Willing to travel, language, other-trial participation | consent_logistics 60/79/68% | **Patient attributes / preferences.** Otherwise they become Doctor questions. |
| Life expectancy, investigator judgement | Common | Neither. These are clinician questions and always Doctor questions. |

Performance status, pregnancy status, biomarkers and weight all fit `Observation`.

## 6. Zetaris findings

**Not run.** The repo has no `.env`, and the session didn't look for credentials elsewhere. `scripts/05_zetaris_probe.sql` contains the full probe:

- 1 REST table for Sample A page 1 (`pageSize=100`, 96 studies), with `CACHE TABLE` and `DESCRIBE`
- 9 SchemaStore views covering every bucket's key fields:
  - nested structs (`ctgov_trial_core`)
  - lists of strings (`_conditions`, `_std_ages`, `_phases`)
  - lists of structs with a nested struct (`_locations` with `geoPoint.lat/lon`)
  - a list inside a list (`_intervention_other_names`, three explodes)
  - MeSH lists (`_condition_mesh`, `_ancestors`)
- a haversine query for recruiting sites within 50 km
- a teardown block

Each statement has an `OUTCOME: NOT RUN` line to fill in. The expected results come from the same raw page (`out/zetaris_expected.json`):

| Check | Expected |
|---|---|
| `ctgov_trial_core` rows | 96 |
| Truncation: `SUM(length(eligibility_text))` / `MAX` | 371,925 / 15,505 |
| Sparse-field inference: `COUNT(maximum_age)` / `COUNT(gender_based)` | 3 / 1 |
| conditions / std_ages / phases rows | 403 / 194 / 131 |
| locations / interventions / other_names rows | 10,428 / 324 / 119 |
| condition_mesh / ancestors rows | 380 / 1,613 |
| Trials with a recruiting site ≤ 50 km | 85 |

Paging, reasoned from the API rather than tested: one REST table is one fixed URL, so it is one page. The next `pageToken` is only known after reading a response, so a multi-page pull needs tokens fetched outside Zetaris, then one `CREATE` + `CACHE` per page, glued together with `UNION ALL`. Sample A fits in one page. Sample B would need 7 tables at `pageSize=100`, or one ~10 MB table at 1,000. **Expectation:** use Zetaris for a single bounded page of at most 1,000 Trials, and the HTTP fallback in `ctgov.py` beyond that.

To run it, put `ZETARIS_API_KEY` in getting-started's `.env.local`, then run `python3 scripts/run_sql.py <path>/05_zetaris_probe.sql` from that repo, or paste one statement at a time into the SQL Editor.

## 7. API caveats

- **Every endpoint and parameter in the plan exists** in the live OpenAPI spec (`spec/oas.yaml`): `filter.geo=distance(lat,lon,Nkm)`, `AREA[StdAge]CHILD`, pipe-separated statuses, and `pageSize` capped at 1,000. `query.locn` wasn't needed.
- **`/stats/field/sizes` fails the whole request** (404) if any requested piece isn't a list itself, such as `InterventionName` or `ConditionMeshTerm`. Query one piece at a time.
- **`geoPoint`**: `/studies/metadata` lists it as a leaf of type `FUNC GeoPoint(...)`, but study JSON returns a `{lat, lon}` struct.
- **`filter.geo` matches on any site, whatever that site's status** (see section 1).
- **The status mix differs in the registry.** Registry-wide, `LocationStatus` is missing for 488,107 studies (`out/registry_enum_stats.csv`), mostly older ones, while recruiting samples have it on at least 99% of studies.
- **Structured vs free-text age.** In A, 21/21 text ages agree with `minimumAge`. In B, 146 agree, 32 differ and 22 have no structured min. In C, 176 agree and 9 differ. Spot checks show most differences are conditional ages ("Karnofsky if ≥ 16 years"), with a few real stricter sub-cohort limits ("Age ≥ 16 during dose escalation").
- **The eligibility text is markdown with escapes** (`\<`, `\>`, `1\.`). Unescape it before splitting or reading thresholds.
- **Splitting.** `criteria.py` isn't implemented, so its docstring rule was used. Studies that didn't split cleanly: 2 / 56 / 64. Causes in B+C: only one heading found (82), no heading at all (35), and a heading with no items (3). Headings also appear as bullets (`* INCLUSION CRITERIA:`) and numbered (`1. Inclusion Criteria:`).
- **Ordering.** Results are unordered by default, so Sample C uses `sort=LastUpdatePostDate:desc` to be reproducible. `countTotal` only works on the first page.
- **Payload size.** A full page of 96 NSCLC trials is 4.0 MB. The recommended `fields=` cuts it by 37.5%. Site lists dominate (10,428 sites).
- **Changes from the plan:**
  - Outputs went to `.scratch/ctgov-discovery/` rather than `scripts/ctgov_discovery/`, `docs/reports/` and `data/trials_snapshot/discovery/`, so nothing is pushed.
  - Python's bundled CA store rejected this machine's TLS chain, so the scripts use the macOS keychain roots exported to `system-ca.pem`.
  - The model pass used Claude in-session, not Nightshift.

## 8. Recommendations

**Fields for `ctgov.fetch`.** Checked against the live API in `out/06_fields.json`:

```
fields=NCTId|BriefTitle|OverallStatus|StudyType|Phase|LastUpdatePostDate|Condition|Keyword|ConditionMeshId|ConditionMeshTerm|ConditionAncestorTerm|EligibilityCriteria|Sex|MinimumAge|MaximumAge|StdAge|HealthyVolunteers|InterventionType|InterventionName|InterventionOtherName|InterventionMeshTerm|LocationFacility|LocationCity|LocationState|LocationCountry|LocationStatus|LocationGeoPoint|CentralContactName|CentralContactEMail|CentralContactPhone
```

**Handle these deterministically, with no model:**
- age and sex gates
- distance to the nearest *recruiting* site
- performance status (scale + threshold, with the scale chosen by age)
- labs with absolute units, and "× ULN" once Facts carry a reference range
- named biomarkers when the Observation is coded
- named prior or current drugs, with `otherNames` and MeSH as synonyms
- body weight

**Use the model, then check deterministically:**
- washout windows and lines of therapy: the model extracts the window and drug class, then date arithmetic runs on Fact `observed_on`
- histology, stage and relapse wording
- measurable disease
- comorbidities, and active vs stable CNS metastases

**Always a Doctor question:** investigator-judgement Criteria, life expectancy, and pregnancy or contraception at screening.

**Before building the matcher:**
1. Add the patient attributes for age, sex and coarse location.
2. Add `ref_low` and `ref_high` to Observation Facts.
3. Run `05_zetaris_probe.sql` to settle whether the 4 MB page and the nested explodes work through Zetaris.

## Files

`.scratch/ctgov-discovery/`:
- `scripts/`: `ctgov_http.py` (cached, rate-limited GET), `01_catalog.py`, `02_samples.py`, `03_coverage.py`, `03b_sites.py`, `04_mine_terms.py`, `04b_model_pass.py`, `05_expected.py`, `05_zetaris_probe.sql`, `06_fields_check.py`
- `out/`: `field_catalog.csv`, `coverage_{A,B,C}.csv`, `registry_enum_stats.csv`, `criteria_categories.csv`, `thresholds.csv`, `model_pass_categories.csv`, and the summary JSON files
- `cache/`: raw responses (59 MB)

Run the scripts from `scripts/` in number order.
