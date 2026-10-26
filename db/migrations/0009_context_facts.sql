-- db/migrations/0009_context_facts.sql — Context Facts of unknown Criterion results (#50), a projected table
-- (app.worldmodel.projector) on a database created from an older db/schema.sql. Safe to run twice. New databases
-- don't need it; db/schema.sql already has it. Verdicts judged before it have no Context Facts (no backfill).
--
--   docker exec -i open-agent-hackathon-clincial-trial-postgres-1 \
--     psql -U trialmatch -d trialmatch -v ON_ERROR_STOP=1 < db/migrations/0009_context_facts.sql
--
-- Then run REGISTER DATASOURCE TABLES FROM trialmatch in Zetaris (db/zetaris_register.sql): the Trials page reads
-- the table through Zetaris.

BEGIN;

CREATE TABLE IF NOT EXISTS criterion_result_context (  -- Context Facts: Facts an unknown result considered that don't settle it.
  nct_id             text NOT NULL,        -- Never a Citation, so never criterion_result.fact_id (its CHECK stands)
  eligibility_hash   text NOT NULL,
  profile_version_id text NOT NULL,
  criterion_id       text NOT NULL,
  ordinal            int  NOT NULL,        -- the Matcher's order
  fact_id            text NOT NULL REFERENCES fact(id),
  PRIMARY KEY (nct_id, eligibility_hash, profile_version_id, criterion_id, ordinal),
  FOREIGN KEY (nct_id, eligibility_hash, profile_version_id, criterion_id) REFERENCES criterion_result ON DELETE CASCADE
);

COMMIT;
