-- =============================================================================
-- Phase 5: can each matchable ClinicalTrials.gov field be read through Zetaris?
-- Run in the Zetaris SQL Editor, ONE statement at a time (or: getting-started/scripts/run_sql.py FILE,
-- which reads ZETARIS_API_KEY from .env.local and stops at the first error).
--
-- STATUS 2026-10-23: NOT RUN. The discovery session had no Zetaris API key (this repo has no .env, and the
-- session did not go looking for credentials). Every OUTCOME line below says "NOT RUN"; replace it with what
-- happened. Expected values for every check are in out/zetaris_expected.json and out/zetaris_expected.csv
-- (computed from the identical raw page by scripts/05_expected.py).
--
-- Source page: Sample A, page 1, pageSize=100 → 96 studies, no nextPageToken, 4,027,909 bytes of JSON.
-- Response shape: top-level object {studies: [ {protocolSection: {...}, derivedSection: {...}, hasResults} ]}
--   = HOWTO §7 case 1 (array-of-structs under a top-level key), with structs 3-4 levels deep and
--   lists-of-structs inside (locations, interventions, meshes) that need a second LATERAL VIEW explode.
--
-- What to record per statement (plan Phase 5 step 3): works / needs backticks / needs second explode /
--   fails on schema inference (sparse fields) / truncates long text.
-- =============================================================================

-- Step 0. No endpoint call.
-- OUTCOME: NOT RUN
CREATE LIGHTNING DATABASE CTGOV_DISCOVERY DESCRIBE BY "ClinicalTrials.gov API v2 field discovery - disposable";

-- Step 1. Calls the endpoint (one GET, ~4 MB). The query string is part of `endpoint`; `|` and `(`, `,`, `)` are
-- pre-encoded so the URL is valid whatever encoding the connector applies.
-- OUTCOME: NOT RUN  (watch for: payload size limit / timeout on a 4 MB body; HTTP 502 → retry once immediately)
CREATE LIGHTNING REST TABLE studies_a_p1 FROM CTGOV_DISCOVERY REQUEST(
    endpoint "https://clinicaltrials.gov/api/v2/studies?query.cond=non-small+cell+lung+cancer&filter.overallStatus=RECRUITING%7CNOT_YET_RECRUITING&filter.geo=distance%28-33.8688%2C151.2093%2C50km%29&pageSize=100",
    method "get",
    response_type "json",
    http_encoding "URLENCODED"
) HEADER (
    user-agent "trialmatch-discovery YOUR_CONTACT_EMAIL"
) BODY ();

-- Step 2. Calls the endpoint once more, then later queries read memory.
-- OUTCOME: NOT RUN
CACHE TABLE ctgov_discovery.studies_a_p1;

-- Step 3. Inspect the inferred schema before writing views. Look for: `studies` as array<struct>, and whether
-- sparse keys (eligibilityModule.maximumAge in 3/96, genderBased in 1/96) made it into the struct.
-- OUTCOME: NOT RUN
DESCRIBE ctgov_discovery.studies_a_p1;

-- Step 4. Container (once per name; no IF NOT EXISTS, skip if it exists).
-- OUTCOME: NOT RUN
CREATE SCHEMASTORE CONTAINER ctgov_discovery;

-- ---------------------------------------------------------------------------
-- Bucket: demographics + trial filters + free text (nested structs, no second explode).
-- Mixed-case keys get backticks (HOWTO §4).
-- Expect 96 rows; SUM(eligibility_len) = 371925, MAX = 15505 (truncation check);
-- COUNT(maximum_age) = 3 and COUNT(gender_based) = 1 (sparse-field inference check).
-- OUTCOME: NOT RUN
CREATE SCHEMASTORE VIEW ctgov_trial_core WITH CONTAINER ctgov_discovery AS
SELECT
    s.`protocolSection`.`identificationModule`.`nctId`                 AS nct_id,
    s.`protocolSection`.`identificationModule`.`briefTitle`            AS title,
    s.`protocolSection`.`statusModule`.`overallStatus`                 AS overall_status,
    s.`protocolSection`.`designModule`.`studyType`                     AS study_type,
    s.`protocolSection`.`designModule`.`enrollmentInfo`.`count`        AS enrollment,
    s.`protocolSection`.`eligibilityModule`.`sex`                      AS sex,
    s.`protocolSection`.`eligibilityModule`.`minimumAge`               AS minimum_age,
    s.`protocolSection`.`eligibilityModule`.`maximumAge`               AS maximum_age,
    s.`protocolSection`.`eligibilityModule`.`healthyVolunteers`        AS healthy_volunteers,
    s.`protocolSection`.`eligibilityModule`.`genderBased`              AS gender_based,
    s.`protocolSection`.`eligibilityModule`.`eligibilityCriteria`      AS eligibility_text,
    length(s.`protocolSection`.`eligibilityModule`.`eligibilityCriteria`) AS eligibility_len
FROM ctgov_discovery.studies_a_p1
LATERAL VIEW explode(studies) AS s;

-- OUTCOME: NOT RUN   (expect 96 | 371925 | 15505 | 3 | 1)
SELECT COUNT(*), SUM(eligibility_len), MAX(eligibility_len), COUNT(maximum_age), COUNT(gender_based)
FROM ctgov_discovery.ctgov_trial_core;

-- ---------------------------------------------------------------------------
-- Lists of strings: second explode. Expect 403 / 194 / 131 rows.
-- OUTCOME: NOT RUN
CREATE SCHEMASTORE VIEW ctgov_trial_conditions WITH CONTAINER ctgov_discovery AS
SELECT s.`protocolSection`.`identificationModule`.`nctId` AS nct_id, c AS condition
FROM ctgov_discovery.studies_a_p1
LATERAL VIEW explode(studies) AS s
LATERAL VIEW explode(s.`protocolSection`.`conditionsModule`.`conditions`) AS c;

-- OUTCOME: NOT RUN
CREATE SCHEMASTORE VIEW ctgov_trial_std_ages WITH CONTAINER ctgov_discovery AS
SELECT s.`protocolSection`.`identificationModule`.`nctId` AS nct_id, a AS std_age
FROM ctgov_discovery.studies_a_p1
LATERAL VIEW explode(studies) AS s
LATERAL VIEW explode(s.`protocolSection`.`eligibilityModule`.`stdAges`) AS a;

-- OUTCOME: NOT RUN
CREATE SCHEMASTORE VIEW ctgov_trial_phases WITH CONTAINER ctgov_discovery AS
SELECT s.`protocolSection`.`identificationModule`.`nctId` AS nct_id, ph AS phase
FROM ctgov_discovery.studies_a_p1
LATERAL VIEW explode(studies) AS s
LATERAL VIEW explode(s.`protocolSection`.`designModule`.`phases`) AS ph;

-- ---------------------------------------------------------------------------
-- Location and access: list of structs with a nested struct (geoPoint). Expect 10428 rows,
-- COUNT(lat) = sites with geoPoint (sum of locations_with_geo in zetaris_expected.csv).
-- OUTCOME: NOT RUN
CREATE SCHEMASTORE VIEW ctgov_trial_locations WITH CONTAINER ctgov_discovery AS
SELECT
    s.`protocolSection`.`identificationModule`.`nctId` AS nct_id,
    l.facility, l.city, l.state, l.country, l.status AS site_status,
    l.`geoPoint`.lat AS lat, l.`geoPoint`.lon AS lon
FROM ctgov_discovery.studies_a_p1
LATERAL VIEW explode(studies) AS s
LATERAL VIEW explode(s.`protocolSection`.`contactsLocationsModule`.`locations`) AS l;

-- Recruiting sites within ~50 km of Sydney, computed in SQL (haversine). Expect 85 distinct nct_id
-- (out/03b_sites.json: of_those_with_a_near_site_recruiting_or_not_yet).
-- OUTCOME: NOT RUN
SELECT COUNT(DISTINCT nct_id) FROM ctgov_discovery.ctgov_trial_locations
WHERE site_status IN ('RECRUITING', 'NOT_YET_RECRUITING')
  AND 6371 * 2 * asin(sqrt(pow(sin(radians(lat - (-33.8688)) / 2), 2)
      + cos(radians(-33.8688)) * cos(radians(lat)) * pow(sin(radians(lon - 151.2093) / 2), 2))) <= 50;

-- ---------------------------------------------------------------------------
-- Treatment: list of structs, and a list of strings inside it (third explode). Expect 324 / 119 rows.
-- OUTCOME: NOT RUN
CREATE SCHEMASTORE VIEW ctgov_trial_interventions WITH CONTAINER ctgov_discovery AS
SELECT s.`protocolSection`.`identificationModule`.`nctId` AS nct_id, i.type AS intervention_type, i.name AS intervention_name
FROM ctgov_discovery.studies_a_p1
LATERAL VIEW explode(studies) AS s
LATERAL VIEW explode(s.`protocolSection`.`armsInterventionsModule`.`interventions`) AS i;

-- OUTCOME: NOT RUN
CREATE SCHEMASTORE VIEW ctgov_trial_intervention_other_names WITH CONTAINER ctgov_discovery AS
SELECT s.`protocolSection`.`identificationModule`.`nctId` AS nct_id, i.name AS intervention_name, o AS other_name
FROM ctgov_discovery.studies_a_p1
LATERAL VIEW explode(studies) AS s
LATERAL VIEW explode(s.`protocolSection`.`armsInterventionsModule`.`interventions`) AS i
LATERAL VIEW explode(i.`otherNames`) AS o;

-- ---------------------------------------------------------------------------
-- Diagnosis: MeSH lists in derivedSection. Expect 380 / 1613 rows.
-- OUTCOME: NOT RUN
CREATE SCHEMASTORE VIEW ctgov_trial_condition_mesh WITH CONTAINER ctgov_discovery AS
SELECT s.`protocolSection`.`identificationModule`.`nctId` AS nct_id, m.id AS mesh_id, m.term AS mesh_term
FROM ctgov_discovery.studies_a_p1
LATERAL VIEW explode(studies) AS s
LATERAL VIEW explode(s.`derivedSection`.`conditionBrowseModule`.`meshes`) AS m;

-- OUTCOME: NOT RUN
CREATE SCHEMASTORE VIEW ctgov_trial_condition_ancestors WITH CONTAINER ctgov_discovery AS
SELECT s.`protocolSection`.`identificationModule`.`nctId` AS nct_id, m.id AS mesh_id, m.term AS mesh_term
FROM ctgov_discovery.studies_a_p1
LATERAL VIEW explode(studies) AS s
LATERAL VIEW explode(s.`derivedSection`.`conditionBrowseModule`.`ancestors`) AS m;

-- Row-count check for every list view in one pass (reads each view once; avoids the
-- MISSING_ATTRIBUTES issue the HOWTO describes for repeated reads of one exploded view).
-- OUTCOME: NOT RUN   (expect 403, 194, 131, 10428, 324, 119, 380, 1613)
SELECT 'conditions', COUNT(*) FROM ctgov_discovery.ctgov_trial_conditions
UNION ALL SELECT 'std_ages', COUNT(*) FROM ctgov_discovery.ctgov_trial_std_ages
UNION ALL SELECT 'phases', COUNT(*) FROM ctgov_discovery.ctgov_trial_phases
UNION ALL SELECT 'locations', COUNT(*) FROM ctgov_discovery.ctgov_trial_locations
UNION ALL SELECT 'interventions', COUNT(*) FROM ctgov_discovery.ctgov_trial_interventions
UNION ALL SELECT 'other_names', COUNT(*) FROM ctgov_discovery.ctgov_trial_intervention_other_names
UNION ALL SELECT 'condition_mesh', COUNT(*) FROM ctgov_discovery.ctgov_trial_condition_mesh
UNION ALL SELECT 'condition_ancestors', COUNT(*) FROM ctgov_discovery.ctgov_trial_condition_ancestors;

-- ---------------------------------------------------------------------------
-- Paging (plan Phase 5 step 4). One REST table = one fixed URL = one page; nextPageToken is only known after
-- the first response, so page N cannot be declared up front. Sample A fits one page (96 ≤ 100), Sample B (608)
-- would need 7 tables at pageSize=100, each a separate CREATE + CACHE, glued with UNION ALL views, and the
-- tokens would have to be fetched outside Zetaris first. Practical answer: Zetaris for a single bounded page
-- (pageSize up to 1000, i.e. ≤ 1000 trials), HTTP fallback in backend/app/trials/ctgov.py for anything longer.
-- Optional check: register pageSize=1000 for Sample B (608 studies, ~10 MB) to find the payload ceiling.
-- OUTCOME: NOT RUN

-- =============================================================================
-- Teardown (HOWTO §3). Views first, then the cached table, then the database.
-- The SchemaStore container has no SQL drop; remove it in the UI / API once viewCount = 0.
-- =============================================================================
-- DROP VIEW ctgov_discovery.ctgov_trial_core;
-- DROP VIEW ctgov_discovery.ctgov_trial_conditions;
-- DROP VIEW ctgov_discovery.ctgov_trial_std_ages;
-- DROP VIEW ctgov_discovery.ctgov_trial_phases;
-- DROP VIEW ctgov_discovery.ctgov_trial_locations;
-- DROP VIEW ctgov_discovery.ctgov_trial_interventions;
-- DROP VIEW ctgov_discovery.ctgov_trial_intervention_other_names;
-- DROP VIEW ctgov_discovery.ctgov_trial_condition_mesh;
-- DROP VIEW ctgov_discovery.ctgov_trial_condition_ancestors;
-- UNCACHE TABLE ctgov_discovery.studies_a_p1;
-- DROP LIGHTNING DATABASE TABLE ctgov_discovery.studies_a_p1;
-- DROP LIGHTNING DATABASE CTGOV_DISCOVERY;
