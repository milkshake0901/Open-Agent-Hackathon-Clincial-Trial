-- db/migrations/0008_fact_flags.sql — how each Fact's observed-on date was settled (#47): fact.flags holds
-- ambiguous_date (a date that reads two ways on a Document with no date order), estimated_date (a relative date such
-- as "4 months ago", counted back from the Document date) and document_date (no date of its own: the Document date),
-- on a database created from an older db/schema.sql. Safe to run twice. New databases don't need it; db/schema.sql
-- already has it. Facts committed before it keep no flags.
--
--   docker exec -i open-agent-hackathon-clincial-trial-postgres-1 \
--     psql -U trialmatch -d trialmatch -v ON_ERROR_STOP=1 < db/migrations/0008_fact_flags.sql
--
-- Then run REGISTER DATASOURCE TABLES FROM trialmatch in Zetaris (db/zetaris_register.sql), and restart the app:
-- Profile versions are read through Zetaris.

BEGIN;

ALTER TABLE fact ADD COLUMN IF NOT EXISTS flags text[] NOT NULL DEFAULT '{}';

COMMIT;
