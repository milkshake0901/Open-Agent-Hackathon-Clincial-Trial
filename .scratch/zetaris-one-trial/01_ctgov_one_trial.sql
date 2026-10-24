-- One-Trial test, step 1: register NCT07680790 from ClinicalTrials.gov API v2 as a Zetaris REST table and flatten it.
-- Run in the Zetaris SQL Editor ONE statement at a time, or:
--   python3 ../ctgov-discovery/ref/run_sql.py 01_ctgov_one_trial.sql      (reads ZETARIS_API_KEY from .env.local)
--
-- Source: GET /studies/NCT07680790 with the field list from ctgov-discovery/scripts/06_fields_check.py.
-- Response shape: ONE study object at the top level {protocolSection, derivedSection}. Unlike /studies there is no
-- `studies[]` array, so the core view needs no explode; lists (locations, meshes) need one.
-- 39 KB of JSON (cached copy: ctgov-discovery/cache/studies_NCT07680790__aef26b732344.json).
--
-- maximumAge is absent for this Trial, so schema inference will not create that column: selecting it would fail with
-- UNRESOLVED_COLUMN. It is left out of ctgov_trial_core on purpose (NULL means "no limit" downstream).
--
-- Expected values (from the cached JSON) are on each OUTCOME line; a mismatch means truncation or an inference gap.

-- Step 0. No endpoint call.
-- OUTCOME: OK 2026-10-24, matched expected
CREATE LIGHTNING DATABASE CTGOV DESCRIBE BY "ClinicalTrials.gov API v2 - one-Trial test";

-- Step 1. Calls the endpoint (one GET, 39 KB). `|` is pre-encoded as %7C.
-- OUTCOME: OK 2026-10-24, matched expected
CREATE LIGHTNING REST TABLE study_nct07680790 FROM CTGOV REQUEST(
    endpoint "https://clinicaltrials.gov/api/v2/studies/NCT07680790?fields=NCTId%7CBriefTitle%7COverallStatus%7CStudyType%7CPhase%7CLastUpdatePostDate%7CCondition%7CKeyword%7CConditionMeshId%7CConditionMeshTerm%7CConditionAncestorTerm%7CEligibilityCriteria%7CSex%7CMinimumAge%7CMaximumAge%7CStdAge%7CHealthyVolunteers%7CInterventionType%7CInterventionName%7CInterventionOtherName%7CInterventionMeshTerm%7CLocationFacility%7CLocationCity%7CLocationState%7CLocationCountry%7CLocationStatus%7CLocationGeoPoint%7CCentralContactName%7CCentralContactEMail%7CCentralContactPhone",
    method "get",
    response_type "json",
    http_encoding "URLENCODED"
) HEADER (
    user-agent "YOUR_APP_NAME YOUR_CONTACT_EMAIL"   -- run_sql.py swaps this exact placeholder for ZETARIS_USER_AGENT
) BODY ();

-- Step 2. A REST table re-fetches on every uncached query; cache it straight away.
-- OUTCOME: OK 2026-10-24, matched expected
CACHE TABLE ctgov.study_nct07680790;

-- Step 3. Expect protocolSection and derivedSection as structs; no maximumAge inside eligibilityModule.
-- OUTCOME: OK 2026-10-24, matched expected
DESCRIBE ctgov.study_nct07680790;

-- Step 4. Container (once per name; no IF NOT EXISTS, skip if it exists).
-- OUTCOME: OK 2026-10-24, matched expected
CREATE SCHEMASTORE CONTAINER ctgov;

-- One row per Trial. Expect 1 row: NCT07680790 | RECRUITING | Non-Small Cell Lung Cancer | ALL | 18 Years | false | 1024
-- OUTCOME: OK 2026-10-24, matched expected
CREATE SCHEMASTORE VIEW ctgov_trial_core WITH CONTAINER ctgov AS
SELECT
    `protocolSection`.`identificationModule`.`nctId`                       AS nct_id,
    `protocolSection`.`identificationModule`.`briefTitle`                  AS title,
    `protocolSection`.`statusModule`.`overallStatus`                       AS overall_status,
    `protocolSection`.`statusModule`.`lastUpdatePostDateStruct`.`date`     AS last_update_posted,
    concat_ws('|', `protocolSection`.`conditionsModule`.`conditions`)      AS conditions,   -- '|'-joined list
    `protocolSection`.`eligibilityModule`.`sex`                            AS sex,
    `protocolSection`.`eligibilityModule`.`minimumAge`                     AS minimum_age,
    `protocolSection`.`eligibilityModule`.`healthyVolunteers`              AS healthy_volunteers,
    `protocolSection`.`eligibilityModule`.`eligibilityCriteria`            AS eligibility_text,
    length(`protocolSection`.`eligibilityModule`.`eligibilityCriteria`)    AS eligibility_len
FROM ctgov.study_nct07680790;

-- One row per site. Expect 201 rows; 5 RECRUITING, 193 NOT_YET_RECRUITING, 3 WITHDRAWN; COUNT(lat) = 183.
-- OUTCOME: OK 2026-10-24, matched expected
CREATE SCHEMASTORE VIEW ctgov_trial_sites WITH CONTAINER ctgov AS
SELECT
    `protocolSection`.`identificationModule`.`nctId` AS nct_id,
    l.facility, l.city, l.state, l.country, l.status AS site_status,
    l.`geoPoint`.lat AS lat, l.`geoPoint`.lon AS lon
FROM ctgov.study_nct07680790
LATERAL VIEW explode(`protocolSection`.`contactsLocationsModule`.`locations`) AS l;

-- Condition MeSH terms. Expect 1 row: Carcinoma, Non-Small-Cell Lung.
-- OUTCOME: OK 2026-10-24, matched expected
CREATE SCHEMASTORE VIEW ctgov_trial_mesh WITH CONTAINER ctgov AS
SELECT
    `protocolSection`.`identificationModule`.`nctId` AS nct_id,
    m.id AS mesh_id, m.term AS mesh_term
FROM ctgov.study_nct07680790
LATERAL VIEW explode(`derivedSection`.`conditionBrowseModule`.`meshes`) AS m;

-- Checks. Expect: 1 | 1024 ;  201 | 183 ;  1
-- OUTCOME: OK 2026-10-24, matched expected
SELECT COUNT(*), MAX(eligibility_len) FROM ctgov.ctgov_trial_core;
-- OUTCOME: OK 2026-10-24, matched expected
SELECT COUNT(*), COUNT(lat) FROM ctgov.ctgov_trial_sites;
-- OUTCOME: OK 2026-10-24, matched expected
SELECT COUNT(*) FROM ctgov.ctgov_trial_mesh;

-- Sites within 50 km of Sydney (haversine). Expect 2 rows, both NOT_YET_RECRUITING (3.8 km and 21.7 km):
-- this Trial has no RECRUITING Sydney site yet.
-- OUTCOME: OK 2026-10-24, matched expected
SELECT facility, site_status,
       6371 * 2 * asin(sqrt(pow(sin(radians(lat - (-33.8688)) / 2), 2)
       + cos(radians(-33.8688)) * cos(radians(lat)) * pow(sin(radians(lon - 151.2093) / 2), 2))) AS km
FROM ctgov.ctgov_trial_sites
WHERE lat IS NOT NULL
  AND 6371 * 2 * asin(sqrt(pow(sin(radians(lat - (-33.8688)) / 2), 2)
      + cos(radians(-33.8688)) * cos(radians(lat)) * pow(sin(radians(lon - 151.2093) / 2), 2))) <= 50;

-- =============================================================================
-- Teardown (HOWTO §3). Views first, then the cached table. The container has no SQL drop.
-- =============================================================================
-- DROP VIEW ctgov.ctgov_trial_core;
-- DROP VIEW ctgov.ctgov_trial_sites;
-- DROP VIEW ctgov.ctgov_trial_mesh;
-- UNCACHE TABLE ctgov.study_nct07680790;
-- DROP LIGHTNING DATABASE TABLE ctgov.study_nct07680790;
