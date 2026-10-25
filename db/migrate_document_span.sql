-- Evidence boxes from Nemotron Parse. Safe to run on a database that already has schema.sql.
CREATE TABLE IF NOT EXISTS document_span (
  id            text PRIMARY KEY,
  document_hash text NOT NULL,
  page          int  NOT NULL,
  ordinal       int  NOT NULL,
  kind          text NOT NULL,
  text          text NOT NULL,
  x0            double precision NOT NULL,
  y0            double precision NOT NULL,
  x1            double precision NOT NULL,
  y1            double precision NOT NULL,
  UNIQUE (document_hash, page, ordinal),
  FOREIGN KEY (document_hash, page) REFERENCES document_page(document_hash, number)
);

ALTER TABLE fact ADD COLUMN IF NOT EXISTS span_id text REFERENCES document_span(id);

-- The running volume was created before these columns were added to schema.sql.
ALTER TABLE document ADD COLUMN IF NOT EXISTS respondent text CHECK (respondent IN ('patient','other'));
ALTER TABLE fact ADD COLUMN IF NOT EXISTS question text;
