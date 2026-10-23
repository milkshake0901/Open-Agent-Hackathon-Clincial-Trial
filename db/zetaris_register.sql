-- Run in the Zetaris SQL Editor, one statement at a time.
-- 1. Register our Postgres so agents read it through Zetaris (ADR 0001).
--    Zetaris runs in Docker: use host.docker.internal, not localhost, to reach our container.
-- TODO: CREATE LIGHTNING DATABASE trialmatch ... (JDBC postgres, host.docker.internal:5433)

-- 2. Register ClinicalTrials.gov API v2 as a REST table (same pattern as the PokéAPI starter in
--    zetaris/getting-started open_data/rest_apis/sql/non_rate_limited/02_pokeapi_create.sql).
-- TODO: CREATE LIGHTNING DATABASE CTGOV_REST ...
-- TODO: CREATE LIGHTNING REST TABLE studies ... (https://clinicaltrials.gov/api/v2/studies)
-- TODO: CREATE SCHEMASTORE VIEW trial_eligibility ... (protocolSection.eligibilityModule.eligibilityCriteria)
