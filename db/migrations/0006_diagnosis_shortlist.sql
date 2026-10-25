-- db/migrations/0006_diagnosis_shortlist.sql — a Diagnosis check offers a shortlist of Condition labels and keeps the
-- ticked ones (#33, ADR 0005), replacing the single suggested term and its confidence, on a database created from an
-- older db/schema.sql. Safe to run twice. New databases don't need it; db/schema.sql already has it. Old checks are
-- not turned into labels (spec #31): a confirmed one keeps no ticked labels, so it holds no Condition term and the
-- Respondent redoes the step; "no" becomes none_of_these and "unclear" becomes not_sure (both left it to the GP).
--
--   docker exec -i open-agent-hackathon-clincial-trial-postgres-1 \
--     psql -U trialmatch -d trialmatch -v ON_ERROR_STOP=1 < db/migrations/0006_diagnosis_shortlist.sql

BEGIN;

ALTER TABLE diagnosis_check ADD COLUMN IF NOT EXISTS shortlist jsonb NOT NULL DEFAULT '[]';
ALTER TABLE diagnosis_check ADD COLUMN IF NOT EXISTS ticked jsonb NOT NULL DEFAULT '[]';
ALTER TABLE diagnosis_check DROP CONSTRAINT IF EXISTS diagnosis_check_status_check;
UPDATE diagnosis_check SET status = CASE status WHEN 'confirmed' THEN 'ticked' WHEN 'rejected' THEN 'none_of_these'
                                                WHEN 'unclear' THEN 'not_sure' ELSE status END;
ALTER TABLE diagnosis_check ADD CONSTRAINT diagnosis_check_status_check
  CHECK (status IN ('proposed','ticked','none_of_these','not_sure'));
ALTER TABLE diagnosis_check DROP COLUMN IF EXISTS suggested_term;
ALTER TABLE diagnosis_check DROP COLUMN IF EXISTS confidence;

COMMIT;
