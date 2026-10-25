-- db/migrations/0008_diagnosis_confirmed.sql — a Diagnosis check confirmed under the single-term design, before
-- Condition labels, is `confirmed` again (#33, ADR 0005), on a database that ran 0006: 0006 made it `ticked` with no
-- ticked labels, and only those checks have none (a Respondent ticks one or more). Nothing it does changes: it still
-- settles the diagnosis, holds no Condition term (spec #31: the Respondent redoes the step) and raises no Doctor
-- question. Safe to run twice, and on a database 0006 never touched. New databases don't need it; db/schema.sql
-- already allows `confirmed`.
--
--   docker exec -i open-agent-hackathon-clincial-trial-postgres-1 \
--     psql -U trialmatch -d trialmatch -v ON_ERROR_STOP=1 < db/migrations/0008_diagnosis_confirmed.sql

BEGIN;

ALTER TABLE diagnosis_check DROP CONSTRAINT IF EXISTS diagnosis_check_status_check;
ALTER TABLE diagnosis_check ADD CONSTRAINT diagnosis_check_status_check
  CHECK (status IN ('proposed','ticked','none_of_these','not_sure','confirmed'));
UPDATE diagnosis_check SET status = 'confirmed' WHERE status = 'ticked' AND ticked = '[]'::jsonb;

COMMIT;
