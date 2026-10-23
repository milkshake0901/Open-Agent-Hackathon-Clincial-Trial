# Plan: find every ClinicalTrials.gov field we can match patients on

For: a coding agent running on the developer's machine, with internet access and a local Zetaris instance.
Output: `docs/reports/ctgov-matchable-variables.md`, plus the scripts and data samples that produced it.

## Goal

Find out what ClinicalTrials.gov API v2 can give us, and which parts of it can be checked against a patient. For each field, the report answers:

1. Is it a structured field (a typed value such as `minimumAge`) or only free text inside `eligibilityCriteria`?
2. How often is it filled in, in trials we would actually match against?
3. Which patient Fact would answer it? Use the `fact.resource` values in `db/schema.sql`: `Condition`, `Observation`, `MedicationStatement`, `Procedure`. Also record when no resource fits.
4. Does it come through Zetaris (a `CREATE LIGHTNING REST TABLE` plus `LATERAL VIEW explode`), or only through direct HTTP?

## Context you need

- Read `README.md`, `GLOSSARY.md`, `DEVELOPER.md` and `docs/adr/0001-write-postgres-read-through-zetaris.md` first. Use the GLOSSARY terms (Trial, Criterion, Fact, Verdict) in the report.
- Today the `trial` table keeps only `nct_id`, `title`, `conditions`, `status` and `eligibility_text`. One question for this work is what we are leaving behind.
- Our Facts have no demographics or location resource. Age, sex and distance to a trial site may have nowhere to live. Confirm or rule this out in the report.
- Zetaris REST-table syntax: see `db/zetaris_register.sql`, and the working example in https://github.com/zetaris/getting-started at `open_data/rest_apis/sql/non_rate_limited/02_pokeapi_create.sql` (the same repo's `open_data/rest_apis/HOWTO.md` covers caching, backticks and known failures).
- API docs: https://clinicaltrials.gov/data-api/api. The base URL is `https://clinicaltrials.gov/api/v2`. No API key is needed.

## Rules

- Stay at or below about 50 requests a minute, and sleep at least 1.3 s between calls. On HTTP 429, wait 60 s and retry once.
- Cache every raw response under `data/trials_snapshot/discovery/` and add that folder to `.gitignore`. Re-runs read the cache; they do not call the API again.
- Never send patient data anywhere. This work only reads public trial data. Nothing goes to an LLM except trial text.
- Don't change app code under `backend/app/`. Put scripts in `scripts/ctgov_discovery/`.
- Before using any endpoint or parameter in this plan, check it against the live docs. If one is wrong or missing, record that in the report and carry on.

## Phase 1: the full field catalog (no studies yet)

Call each endpoint, save the response, and write `01_catalog.py` to produce `field_catalog.csv`.

| Call | What it gives |
|---|---|
| `GET /version` | API version and data timestamp. Put both in the report header. |
| `GET /studies/metadata` | Every field as a tree: piece name, path, type, whether it is a list, and description. |
| `GET /studies/enums` | Allowed values for each enum field (status, phase, sex, std ages, etc.). |
| `GET /studies/search-areas` | Which fields `query.*` parameters search. This tells us what we can filter on server-side. |
| `GET /stats/size` | Total study count. |

`field_catalog.csv` has one row per leaf field, with these columns: `path`, `piece_name`, `type`, `is_list`, `enum_values`, `description`, `searchable_by`.

## Phase 2: choose the trial samples

Coverage depends on the kind of trial, so measure it on trials we would really match against, not the whole registry.

- **Sample A (target):** `query.cond=non-small cell lung cancer`, `filter.overallStatus=RECRUITING|NOT_YET_RECRUITING`, plus a location filter near Sydney, matching `docs/architecture.md`. If you don't know the right `filter.geo` value, use `query.locn=Sydney`.
- **Sample B (paediatric oncology):** `query.cond=neuroblastoma OR medulloblastoma OR leukemia` with `query.term=AREA[StdAge]CHILD`, recruiting. Check the `AREA[]` syntax in the docs.
- **Sample C (control):** 500 recruiting interventional studies with no condition filter.

For each sample, fetch every page by following `nextPageToken`, with `pageSize=1000` and no `fields` filter, so you get the full records. Cap each sample at 2,000 studies. Record the counts in the report.

## Phase 3: structured field coverage

Write `03_coverage.py`. For each sample and each leaf path in `field_catalog.csv`, compute:

- the share of studies where it is present and not empty;
- the number of distinct values, and the top 10 values for enums and short strings;
- for lists, the median and maximum length.

Also call `GET /stats/field/values?fields=<piece>` for the enum fields to get registry-wide distributions, and `GET /stats/field/sizes` for list sizes. Compare them with the sample numbers.

Then sort the fields into these buckets. A field can belong to more than one.

| Bucket | Examples to look for |
|---|---|
| Patient demographics | `eligibilityModule.sex`, `minimumAge`, `maximumAge`, `stdAges`, `healthyVolunteers`, `genderBased` |
| Diagnosis | `conditionsModule.conditions`, `keywords`, `derivedSection.conditionBrowseModule` (MeSH terms and ancestors) |
| Treatment history and exclusions | `armsInterventionsModule.interventions` (type, name, otherNames), `derivedSection.interventionBrowseModule` |
| Location and access | `contactsLocationsModule.locations` (facility, city, country, `geoPoint`, per-site `status`), central contacts |
| Trial filters (not patient) | `statusModule.overallStatus`, `designModule.phases`, `studyType`, `enrollmentInfo`, dates |
| Free text to parse | `eligibilityModule.eligibilityCriteria`, `descriptionModule.briefSummary` and `detailedDescription` |
| Not useful for matching | everything else, with one line on why |

## Phase 4: what eligibility free text asks about

Most of what we can match on is only in `eligibilityCriteria`. Find out what patient variables it mentions.

1. **Split.** Split each study's text into inclusion and exclusion Criteria, using the same rule as `backend/app/trials/criteria.py` if it is implemented. If it isn't, split on the "Inclusion Criteria:" and "Exclusion Criteria:" headings and on bullets. Record how many studies don't split cleanly.
2. **Dictionary pass (deterministic, in `04_mine_terms.py`).** Tag each Criterion with any of these categories, using regexes or keyword lists. Count the share of studies, per sample, that mention each one.
   - Age and sex (repeats the structured fields; note any disagreement)
   - Diagnosis and histology confirmation; stage, grade or risk group; relapsed or refractory status
   - Biomarkers and genetics: EGFR, ALK, ROS1, KRAS, BRAF, MET, RET, NTRK, HER2, PD-L1, MSI/dMMR, TMB, MYCN, H3K27M, fusions, germline variants
   - Performance status: ECOG, Karnofsky, Lansky
   - Labs and organ function: ANC, platelets, haemoglobin, bilirubin, ALT/AST, creatinine/eGFR/CrCl, INR, LVEF or QTc. Capture the threshold and unit as written (e.g. `ANC ≥ 1.5 × 10⁹/L`).
   - Measurable disease: RECIST, INRC, RANO
   - Prior treatment: lines of therapy, specific drugs or classes, radiotherapy, surgery, transplant, washout periods
   - CNS or brain metastases
   - Comorbidities and infections: HIV, HBV, HCV, autoimmune disease, cardiac history, other cancers
   - Current medications and interactions: CYP3A4, steroids, anticoagulants
   - Pregnancy, breastfeeding and contraception
   - Consent and logistics: life expectancy, willing to travel, language
3. **Model pass (optional).** For 50 random Criteria per sample that the dictionary didn't tag, ask the model to name the patient variable each one needs. Add any new categories that show up three or more times. Mark these as model-derived in the report.
4. **Thresholds.** For the lab and age categories, report how often a numeric threshold with a unit can be pulled out reliably. That tells us whether a Criterion could be checked deterministically, without a model.

## Phase 5: check Zetaris retrieval

On the local Zetaris instance, in the SQL Editor, one statement at a time:

1. `CREATE LIGHTNING DATABASE CTGOV_DISCOVERY`, then one `CREATE LIGHTNING REST TABLE` for Sample A's first page (`pageSize=100`), then `CACHE TABLE`.
2. `CREATE SCHEMASTORE VIEW`s that explode `studies`. Then try each bucket's key fields: nested structs (`protocolSection.eligibilityModule.*`), lists of strings (`conditions`, `stdAges`), lists of structs (`locations` with `geoPoint`, `interventions`), and the MeSH lists in `derivedSection`.
3. For each field, record whether it works, needs backticks, needs a second `explode`, fails because of schema inference (sparse fields), or truncates long text (check that `eligibilityCriteria` length matches the raw JSON).
4. Confirm that one REST table means one page. Record what a multi-page pull costs: one table per page joined with `UNION ALL`, or the HTTP fallback in `backend/app/trials/ctgov.py`.

Save the statements you ran as `scripts/ctgov_discovery/05_zetaris_probe.sql`, with a comment beside each one giving its outcome. Drop the views and tables afterwards (see the teardown section in the Zetaris HOWTO).

## Phase 6: the report

Write `docs/reports/ctgov-matchable-variables.md` with these sections:

1. **Summary.** In five to eight bullets: the variables we can match on, which are structured and which are free text only, and the biggest gaps.
2. **Run details.** API version and data timestamp, the sample queries and counts, the date, and the Zetaris version.
3. **Matchable variables table.** One row per patient variable (not per API field), with these columns:
   `variable` | `source` (structured path or free-text category) | `coverage A / B / C` | `patient Fact resource` (or "none: gap") | `deterministic check possible?` | `Zetaris OK?` | `notes`
4. **Structured fields we don't store today.** The fields `trial` currently drops that the matcher or UI would use, such as `minimumAge`, `maximumAge`, `sex`, `stdAges`, `locations` with `geoPoint`, `phases` and MeSH terms. Give a proposed column for each, but don't change the schema.
5. **Gaps in our patient model.** Variables trials ask about that our Fact resources can't hold. Expect at least age/date of birth, sex and patient location. Say whether each could be a Fact or needs a patient attribute.
6. **Zetaris findings.** What works, what needs workarounds, and what fails, with the SQL that worked.
7. **API caveats.** Rate limits, paging, missing fields, inconsistencies between structured and free-text values, and anything in this plan that turned out wrong.
8. **Recommendations.** The fields to fetch (a concrete `fields=` list for `ctgov.fetch`), and which Criterion categories to handle deterministically versus with a model.

Attach `field_catalog.csv` and the per-sample coverage CSVs under `docs/reports/ctgov-discovery/` (they're small). Raw JSON stays in the ignored cache.

## Done when

- `docs/reports/ctgov-matchable-variables.md` exists, and every number in it comes from a script in `scripts/ctgov_discovery/` that re-runs from the cache.
- Every variable in the matchable table has a coverage figure, a Fact mapping or a stated gap, and a Zetaris result.
- Nothing under `backend/app/` or `db/schema.sql` has changed.
