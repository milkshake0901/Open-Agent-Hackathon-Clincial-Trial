-- db/migrations/0002_closed_trials.sql — brings a database created from an older db/schema.sql up to date with
-- Closed trials (#23, ADR 0004): the registry dates a Closed trial's 15-year cutoff is taken from, and the flag a
-- later ingest sets on one that aged past it. Additive only. Safe to run twice.
-- New databases don't need it; db/schema.sql already has all of this.
--
--   docker exec -i open-agent-hackathon-clincial-trial-postgres-1 \
--     psql -U trialmatch -d trialmatch -v ON_ERROR_STOP=1 < db/migrations/0002_closed_trials.sql

BEGIN;

ALTER TABLE trial ADD COLUMN IF NOT EXISTS primary_completion_date date;
ALTER TABLE trial ADD COLUMN IF NOT EXISTS completion_date date;
ALTER TABLE trial ADD COLUMN IF NOT EXISTS last_update_date date;
ALTER TABLE trial ADD COLUMN IF NOT EXISTS dropped boolean NOT NULL DEFAULT false;

COMMIT;
