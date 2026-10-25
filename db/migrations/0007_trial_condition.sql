-- db/migrations/0007_trial_condition.sql — each Trial's Condition labels, normalised once in a projected table
-- (trial_condition, ADR 0005) that Condition label counts, searches and the Trials a Condition term selects read, on
-- a database created from an older db/schema.sql. Safe to run twice. New databases don't need it; db/schema.sql
-- already has it. Fills the table from trial.conditions with the keys app.trials.label_key and label_words give
-- (Postgres lower() for Python's casefold(): the same for every label but a few non-English letters such as ß;
-- scripts/rebuild_projections.py rebuilds it exactly from the World Model).
--
--   docker exec -i open-agent-hackathon-clincial-trial-postgres-1 \
--     psql -U trialmatch -d trialmatch -v ON_ERROR_STOP=1 < db/migrations/0007_trial_condition.sql
--
-- Then run REGISTER DATASOURCE TABLES FROM trialmatch in Zetaris (db/zetaris_register.sql): a Re-scan reads the
-- table through Zetaris.

BEGIN;

CREATE TABLE IF NOT EXISTS trial_condition (
  nct_id           text NOT NULL REFERENCES trial(nct_id),
  label_key        text NOT NULL,
  label            text NOT NULL,
  words            text NOT NULL,
  PRIMARY KEY (nct_id, label_key)
);
CREATE INDEX IF NOT EXISTS trial_condition_by_key ON trial_condition (label_key);

-- One row per (Trial, label key), spelled as the Trial's last label with that key; blank labels are left out.
INSERT INTO trial_condition (nct_id, label_key, label, words)
SELECT DISTINCT ON (nct_id, label_key) nct_id, label_key, label,
       btrim(regexp_replace(lower(label), '[^a-z0-9]+', ' ', 'g'))
FROM (SELECT t.nct_id, c.label, c.ordinal,
             btrim(regexp_replace(lower(c.label), '\s+', ' ', 'g')) AS label_key
      FROM trial t CROSS JOIN LATERAL unnest(t.conditions) WITH ORDINALITY AS c(label, ordinal)) labels
WHERE label_key <> ''
ORDER BY nct_id, label_key, ordinal DESC
ON CONFLICT (nct_id, label_key) DO NOTHING;

COMMIT;
