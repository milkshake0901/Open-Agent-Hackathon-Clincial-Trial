-- Run in the Zetaris SQL Editor, one statement at a time.
-- 1. Register our Postgres so agents read it through Zetaris (ADR 0001).
--    Zetaris runs in Docker: use host.docker.internal, not localhost, to reach our container.
--    JDBC sources use CREATE DATASOURCE, not CREATE LIGHTNING DATABASE (getting-started
--    docs/guides/zetaris-lightning-sql-commands.md §4.1); tables are then <datasource>.<table>, e.g. trialmatch.criterion.
--    Credentials are the local docker-compose.yml defaults.
CREATE DATASOURCE trialmatch DESCRIBE BY "TrialMatch Postgres (World Model projections)" OPTIONS (
  jdbcdriver "org.postgresql.Driver",
  jdbcurl "jdbc:postgresql://host.docker.internal:5433/trialmatch",
  username "trialmatch",
  password "trialmatch",
  fetchsize "1000"
);
-- Import table metadata; re-run after a schema change (each db/migrations/*.sql that adds a table says so).
-- Agents read: trial, criterion, trial_site, trial_contact, trial_outcome, trial_outcome_value, trial_publication,
-- fact, profile_version, profile_version_fact, verdict, criterion_result, doctor_question, respondent_question.
REGISTER DATASOURCE TABLES FROM trialmatch;

-- 2. Register ClinicalTrials.gov API v2 as a REST table (same pattern as the PokéAPI starter in
--    zetaris/getting-started open_data/rest_apis/sql/non_rate_limited/02_pokeapi_create.sql).
--    One-Trial test version (NCT07680790): .scratch/zetaris-one-trial/01_ctgov_one_trial.sql
-- TODO: CREATE LIGHTNING DATABASE CTGOV_REST ...
-- TODO: CREATE LIGHTNING REST TABLE studies ... (https://clinicaltrials.gov/api/v2/studies)
-- TODO: CREATE SCHEMASTORE VIEW trial_eligibility ... (protocolSection.eligibilityModule.eligibilityCriteria)
