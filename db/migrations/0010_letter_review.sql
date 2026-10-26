-- db/migrations/0010_letter_review.sql — Letter review (#48): document.document_date holds a Document date the
-- Respondent corrected in Letter review (NULL: as read from the Document's first page), and fact.checked says whether
-- the Respondent checked a letter Fact before it was committed ("checked by you" / "not checked"), on a database
-- created from an older db/schema.sql. Safe to run twice. New databases don't need it; db/schema.sql already has
-- both. Facts committed before it are not checked.
--
--   docker exec -i open-agent-hackathon-clincial-trial-postgres-1 \
--     psql -U trialmatch -d trialmatch -v ON_ERROR_STOP=1 < db/migrations/0010_letter_review.sql
--
-- Then run REGISTER DATASOURCE TABLES FROM trialmatch in Zetaris (db/zetaris_register.sql), and restart the app:
-- Profile versions are read through Zetaris.

BEGIN;

ALTER TABLE document ADD COLUMN IF NOT EXISTS document_date date;
ALTER TABLE fact ADD COLUMN IF NOT EXISTS checked boolean NOT NULL DEFAULT false;

COMMIT;
