-- db/migrations/0001_intake_questionnaire.sql — brings a database created from the pre-questionnaire
-- db/schema.sql up to date with the Intake questionnaire (spec #5, tickets #6–#16). Additive only: no table,
-- column or row is dropped, so the trial row and criteria Zetaris already reads are kept. Safe to run twice.
-- New databases don't need it; db/schema.sql already has all of this.
--
--   docker exec -i open-agent-hackathon-clincial-trial-postgres-1 \
--     psql -U trialmatch -d trialmatch -v ON_ERROR_STOP=1 < db/migrations/0001_intake_questionnaire.sql

BEGIN;

-- ---------- record ----------
ALTER TABLE document ADD COLUMN IF NOT EXISTS respondent text CHECK (respondent IN ('patient','other'));
ALTER TABLE fact ADD COLUMN IF NOT EXISTS question text;

ALTER TABLE fact DROP CONSTRAINT IF EXISTS fact_resource_check;
ALTER TABLE fact ADD CONSTRAINT fact_resource_check
  CHECK (resource IN ('Condition','Observation','MedicationStatement','Procedure','Patient','AllergyIntolerance'));

CREATE TABLE IF NOT EXISTS diagnosis_check (
  id             text PRIMARY KEY,
  patient_id     text NOT NULL REFERENCES patient(id),
  text           text NOT NULL,
  suggested_term text,
  confidence     real NOT NULL,
  status         text NOT NULL CHECK (status IN ('proposed','confirmed','rejected','not_sure','unclear')),
  created_at     timestamptz NOT NULL,
  answered_at    timestamptz,
  settled_seq    bigint
);
CREATE SEQUENCE IF NOT EXISTS diagnosis_check_settled;
CREATE INDEX IF NOT EXISTS diagnosis_check_by_patient ON diagnosis_check (patient_id, settled_seq);

CREATE TABLE IF NOT EXISTS return_token (
  token_hash    text PRIMARY KEY,
  patient_id    text NOT NULL UNIQUE REFERENCES patient(id),
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS search_preference (
  patient_id    text PRIMARY KEY REFERENCES patient(id),
  postcode      text,
  lat           double precision,
  lon           double precision,
  max_travel_km int,
  contact       text,
  updated_at    timestamptz NOT NULL DEFAULT now()
);

-- ---------- trials ----------
CREATE TABLE IF NOT EXISTS trial_site (
  nct_id           text NOT NULL REFERENCES trial(nct_id),
  ordinal          int  NOT NULL,
  facility         text NOT NULL,
  city             text NOT NULL,
  country          text NOT NULL,
  status           text NOT NULL,
  lat              double precision,
  lon              double precision,
  PRIMARY KEY (nct_id, ordinal)
);

-- ---------- matching ----------
ALTER TABLE criterion_result ADD COLUMN IF NOT EXISTS ask text;

CREATE TABLE IF NOT EXISTS respondent_question (
  nct_id             text NOT NULL,
  eligibility_hash   text NOT NULL,
  profile_version_id text NOT NULL,
  criterion_id       text NOT NULL REFERENCES criterion(id),
  question_id        text NOT NULL,
  question           text NOT NULL,
  subject            text NOT NULL,
  text               text NOT NULL,
  PRIMARY KEY (nct_id, eligibility_hash, profile_version_id, criterion_id),
  FOREIGN KEY (nct_id, eligibility_hash, profile_version_id) REFERENCES verdict ON DELETE CASCADE
);

COMMIT;
