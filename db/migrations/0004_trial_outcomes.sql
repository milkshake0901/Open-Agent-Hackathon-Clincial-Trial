-- db/migrations/0004_trial_outcomes.sql — adds a Trial's Outcomes (#25): the has-results flag on trial, and
-- trial_outcome, trial_outcome_value and trial_publication, to a database created from an older db/schema.sql.
-- Additive only. Safe to run twice. New databases don't need it; db/schema.sql already has all of this.
-- Existing Trials get their Outcomes on the next ingest (the new Outcome fields count as a change), or at once from
-- backend/scripts/rebuild_projections.py for events already recorded with them. Then re-run
-- REGISTER DATASOURCE TABLES FROM trialmatch in Zetaris (db/zetaris_register.sql) so agents can read the new tables.
--
--   docker exec -i open-agent-hackathon-clincial-trial-postgres-1 \
--     psql -U trialmatch -d trialmatch -v ON_ERROR_STOP=1 < db/migrations/0004_trial_outcomes.sql

BEGIN;

ALTER TABLE trial ADD COLUMN IF NOT EXISTS has_results boolean NOT NULL DEFAULT false;

CREATE TABLE IF NOT EXISTS trial_outcome (
  nct_id           text NOT NULL REFERENCES trial(nct_id),
  kind             text NOT NULL CHECK (kind IN ('primary','secondary','other','result')),
  ordinal          int  NOT NULL,
  title            text NOT NULL,
  description      text NOT NULL,
  time_frame       text NOT NULL,
  type             text NOT NULL,
  unit             text NOT NULL,
  param_type       text NOT NULL,
  PRIMARY KEY (nct_id, kind, ordinal)
);

CREATE TABLE IF NOT EXISTS trial_outcome_value (
  nct_id           text NOT NULL REFERENCES trial(nct_id),
  result_ordinal   int  NOT NULL,
  ordinal          int  NOT NULL,
  group_title      text NOT NULL,
  label            text NOT NULL,
  value            text NOT NULL,
  spread           text NOT NULL,
  lower_limit      text NOT NULL,
  upper_limit      text NOT NULL,
  PRIMARY KEY (nct_id, result_ordinal, ordinal)
);

CREATE TABLE IF NOT EXISTS trial_publication (
  nct_id           text NOT NULL REFERENCES trial(nct_id),
  ordinal          int  NOT NULL,
  pmid             text NOT NULL,
  type             text NOT NULL,
  citation         text NOT NULL,
  PRIMARY KEY (nct_id, ordinal)
);

COMMIT;
