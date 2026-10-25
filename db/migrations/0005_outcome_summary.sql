-- db/migrations/0005_outcome_summary.sql — adds outcome_summary (#26), the cache of plain-language Outcome summaries,
-- to a database created from an older db/schema.sql. Additive only. Safe to run twice. New databases don't need it;
-- db/schema.sql already has it. Summaries are written the first time a Closed trial's Outcomes are opened, so the
-- table starts empty; scripts/rebuild_projections.py refills it from the World Model event log.
--
--   docker exec -i open-agent-hackathon-clincial-trial-postgres-1 \
--     psql -U trialmatch -d trialmatch -v ON_ERROR_STOP=1 < db/migrations/0005_outcome_summary.sql

BEGIN;

CREATE TABLE IF NOT EXISTS outcome_summary (            -- plain-language summary of a Closed trial's Outcomes (#26), written lazily
                                           -- on first open; immutable per (nct, Outcome content hash), old rows kept
  nct_id           text NOT NULL REFERENCES trial(nct_id),
  outcomes_hash    text NOT NULL,         -- sha256 of the Outcomes' canonical JSON it was written for
  summary          text NOT NULL,
  model            text NOT NULL,         -- the model that answered
  written_at       timestamptz NOT NULL,
  PRIMARY KEY (nct_id, outcomes_hash)
);

COMMIT;
