-- One-Trial test, step 5: one Virtual Data Mart over CT.gov views + our Postgres + criterion_topic.
-- Syntax from getting-started docs/guides/zetaris-lightning-sql-commands.md §17 (unverified when written).

-- OUTCOME: OK 2026-10-24, matched expected
CREATE DATAMART trialmatch_mart DESCRIBE BY 'TrialMatch patient Facts, CT.gov Trials, Criterion topics';   -- only letters, digits, space, _ . - ,

-- OUTCOME: OK 2026-10-24, matched expected
ADD DATAMART TABLE trial_core INTO trialmatch_mart FROM ctgov.ctgov_trial_core
  VSCHEMA (nct_id nct_id, title title, overall_status overall_status, last_update_posted last_update_posted,
           conditions conditions, sex sex, minimum_age minimum_age, healthy_volunteers healthy_volunteers,
           eligibility_text eligibility_text, eligibility_len eligibility_len);

-- OUTCOME: OK 2026-10-24, matched expected
ADD DATAMART TABLE trial_sites INTO trialmatch_mart FROM ctgov.ctgov_trial_sites
  VSCHEMA (nct_id nct_id, facility facility, city city, state state, country country, site_status site_status,
           lat lat, lon lon);

-- OUTCOME: OK 2026-10-24, matched expected
ADD DATAMART TABLE trial_mesh INTO trialmatch_mart FROM ctgov.ctgov_trial_mesh
  VSCHEMA (nct_id nct_id, mesh_id mesh_id, mesh_term mesh_term);

-- OUTCOME: OK 2026-10-24, matched expected
ADD DATAMART TABLE criterion INTO trialmatch_mart FROM trialmatch.criterion
  VSCHEMA (id id, nct_id nct_id, eligibility_hash eligibility_hash, kind kind, ordinal ordinal, text text);

-- OUTCOME: OK 2026-10-24, matched expected
ADD DATAMART TABLE criterion_topic INTO trialmatch_mart FROM trialmatch_views.criterion_topic
  VSCHEMA (criterion_id criterion_id, nct_id nct_id, eligibility_hash eligibility_hash, kind kind, ordinal ordinal,
           topic topic);

-- OUTCOME: OK 2026-10-24, matched expected
ADD DATAMART TABLE fact INTO trialmatch_mart FROM trialmatch.fact
  VSCHEMA (id id, document_hash document_hash, page page, resource resource, subject subject, value value,
           unit unit, observed_on observed_on, quote quote, created_at created_at);

-- Pass check A: Criterion 4 once per RECRUITING site (expect 5 rows, none in Sydney).
-- OUTCOME: OK 2026-10-24, matched expected
SELECT c.ordinal, c.text, s.facility, s.city, s.country
FROM trialmatch_mart.criterion_topic t
JOIN trialmatch_mart.criterion   c ON c.id = t.criterion_id
JOIN trialmatch_mart.trial_sites s ON s.nct_id = c.nct_id
WHERE t.topic = 'performance_status' AND s.site_status = 'RECRUITING';

-- Pass check B: Criterion 4 once per site within 50 km of Sydney (expect 2 rows, both NOT_YET_RECRUITING).
-- OUTCOME: OK 2026-10-24, matched expected
SELECT c.ordinal, c.text, s.facility, s.site_status
FROM trialmatch_mart.criterion_topic t
JOIN trialmatch_mart.criterion   c ON c.id = t.criterion_id
JOIN trialmatch_mart.trial_sites s ON s.nct_id = c.nct_id
WHERE t.topic = 'performance_status'
  AND s.lat IS NOT NULL
  AND 6371 * 2 * asin(sqrt(pow(sin(radians(s.lat + 33.8688) / 2), 2)
      + cos(radians(-33.8688)) * cos(radians(s.lat)) * pow(sin(radians(s.lon - 151.2093) / 2), 2))) <= 50;

-- Teardown:
-- DROP DATAMART trialmatch_mart;
