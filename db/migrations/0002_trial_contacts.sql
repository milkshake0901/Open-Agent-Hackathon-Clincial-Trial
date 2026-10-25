-- db/migrations/0002_trial_contacts.sql — adds trial_contact (#27) to a database created from an older
-- db/schema.sql. Additive only. Safe to run twice. New databases don't need it.
-- Existing Trials get their contacts on the next ingest (the new contact fields count as a change).
--
--   docker exec -i open-agent-hackathon-clincial-trial-postgres-1 \
--     psql -U trialmatch -d trialmatch -v ON_ERROR_STOP=1 < db/migrations/0002_trial_contacts.sql

BEGIN;

CREATE TABLE IF NOT EXISTS trial_contact (
  nct_id           text NOT NULL REFERENCES trial(nct_id),
  kind             text NOT NULL CHECK (kind IN ('sponsor','responsible_party','central','official','site')),
  site_ordinal     int  NOT NULL DEFAULT 0,
  ordinal          int  NOT NULL,
  name             text NOT NULL,
  role             text NOT NULL,
  email            text NOT NULL,
  phone            text NOT NULL,
  affiliation      text NOT NULL,
  title            text NOT NULL,
  PRIMARY KEY (nct_id, kind, site_ordinal, ordinal)
);

COMMIT;
