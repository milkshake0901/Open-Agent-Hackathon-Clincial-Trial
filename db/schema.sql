-- db/schema.sql — Postgres for the app (our own container, separate from Zetaris's internal postgres).
-- One writer per table:
--   patient, document, document_page                    app.record.repo
--   search_preference                                   app.record.repo (postcode and its coarse point, travel, contact)
--   return_token                                        app.record.repo (sha256 of the return link's token)
--   diagnosis_check                                     app.record.repo (Diagnosis checks and their answers)
--   wm_event, wm_audit                                  app.worldmodel.store.PgEventStore (engine log)
--   fact, profile_version, profile_version_fact         app.worldmodel.projector, inside the wm_event append
--   trial, trial_condition, criterion, trial_site,      transaction (projections of the World Model, ADR 0001)
--   trial_contact, trial_outcome, trial_outcome_value,
--   trial_publication, outcome_summary
--   verdict, criterion_result, doctor_question,
--   respondent_question
--   trace_run, trace_event, llm_call                    app.trace
-- Facts are append-only. Everything is read through Zetaris by agents.

-- ---------- record ----------
CREATE TABLE patient (
  id            text PRIMARY KEY,
  label         text NOT NULL,            -- de-identified display label, e.g. "Demo patient A"
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE search_preference (          -- per patient, NOT Facts: never rendered into a Document, never in a prompt (ADR 0003)
  patient_id    text PRIMARY KEY REFERENCES patient(id),
  postcode      text,                     -- never shown back, never in a URL, never read for distances (#16)
  lat           double precision,         -- the postcode's coarse location point, computed when it is stored;
  lon           double precision,         -- NULL: no postcode, or one not in app.record.postcodes. Distances read this
  max_travel_km int,                      -- NULL: no limit ("anywhere", or not answered)
  contact       text,                     -- optional email or phone for "you have new questions" notices
  updated_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE return_token (               -- private return link; only the sha256 of the token is stored
  token_hash    text PRIMARY KEY,
  patient_id    text NOT NULL UNIQUE REFERENCES patient(id),   -- one per patient, issued on first submission
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE diagnosis_check (            -- Diagnosis checks: the Condition labels offered for the free-text diagnosis and the
                                          -- Respondent's answer (#14, #33, ADR 0005); NOT Facts: the diagnosis Fact keeps the
                                          -- Respondent's words as its quote
  id             text PRIMARY KEY,
  patient_id     text NOT NULL REFERENCES patient(id),
  text           text NOT NULL,           -- the words the shortlist was made from (the answer, or a re-wording)
  shortlist      jsonb NOT NULL,          -- [{label, open, closed}] offered, in order of fit; empty when none fit
  ticked         jsonb NOT NULL,          -- the labels ticked (from shortlist): the Condition term; [] unless ticked
  status         text NOT NULL CHECK (status IN ('proposed','ticked','none_of_these','not_sure','confirmed')),
                                          -- confirmed: before Condition labels, holds no Condition term (0008)
  created_at     timestamptz NOT NULL,
  answered_at    timestamptz,
  settled_seq    bigint                   -- set from diagnosis_check_settled when ticked / not_sure; the latest
                                          -- settled check holds (a clock can repeat, a sequence cannot)
);
CREATE SEQUENCE diagnosis_check_settled;
CREATE INDEX diagnosis_check_by_patient ON diagnosis_check (patient_id, settled_seq);

CREATE TABLE document (
  hash          text PRIMARY KEY,         -- sha256 of uploaded bytes; identity per GLOSSARY
  patient_id    text NOT NULL REFERENCES patient(id),
  filename      text NOT NULL,
  page_count    int  NOT NULL,
  respondent    text CHECK (respondent IN ('patient','other')),   -- set only on an Intake questionnaire (ADR 0003)
  uploaded_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE document_page (               -- de-identified text only; raw bytes stay on disk
  document_hash text NOT NULL REFERENCES document(hash),
  number        int  NOT NULL,            -- 1-based
  text          text NOT NULL,
  tables_json   jsonb NOT NULL DEFAULT '[]',
  PRIMARY KEY (document_hash, number)
);

CREATE TABLE fact (                        -- FHIR-lite, one table with resource discriminator (append-only)
  id            text PRIMARY KEY,
  document_hash text NOT NULL REFERENCES document(hash),
  page          int  NOT NULL,
  resource      text NOT NULL CHECK (resource IN ('Condition','Observation','MedicationStatement','Procedure',
                                                  'Patient','AllergyIntolerance')),
  subject       text NOT NULL,
  value         text NOT NULL,
  unit          text,
  observed_on   date NOT NULL,
  quote         text NOT NULL,
  question      text,                     -- "Q3" for a Patient-reported Fact from an Intake questionnaire
  created_at    timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (document_hash, page) REFERENCES document_page(document_hash, number)
);
CREATE INDEX fact_subject_date ON fact (subject, observed_on);

CREATE TABLE profile_version (
  id            text PRIMARY KEY,
  patient_id    text NOT NULL REFERENCES patient(id),
  number        int  NOT NULL,
  document_hash text NOT NULL UNIQUE REFERENCES document(hash),   -- one version per accepted Document (idempotency)
  created_at    timestamptz NOT NULL DEFAULT now(),
  UNIQUE (patient_id, number)
);

CREATE TABLE profile_version_fact (        -- a version is a SET of fact ids, never a copy
  profile_version_id text NOT NULL REFERENCES profile_version(id),
  fact_id            text NOT NULL REFERENCES fact(id),
  PRIMARY KEY (profile_version_id, fact_id)
);

-- ---------- trials ----------
CREATE TABLE trial (
  nct_id           text PRIMARY KEY,
  title            text NOT NULL,
  conditions       text[] NOT NULL,
  status           text NOT NULL,
  eligibility_text text NOT NULL,
  eligibility_hash text NOT NULL,
  source           text NOT NULL,         -- 'zetaris' | 'http'
  fetched_at       timestamptz NOT NULL,
  primary_completion_date date,           -- registry dates (a month-only date is its 1st); a Closed trial's cutoff
  completion_date         date,           -- is the first of these three that is given (ADR 0004)
  last_update_date        date,
  dropped          boolean NOT NULL DEFAULT false, -- a later ingest no longer keeps it (aged past 15 years, withdrawn, no Australian site)
  has_results      boolean NOT NULL DEFAULT false  -- the registry's has-results flag (#25)
);

CREATE TABLE trial_condition (             -- the Trial's Condition labels (ADR 0005), normalised once as the trial row is
                                           -- written: what Condition label counts, searches and selection read
  nct_id           text NOT NULL REFERENCES trial(nct_id),
  label_key        text NOT NULL,         -- the label casefolded, whitespace runs as one space: labels equal on it are one
  label            text NOT NULL,         -- the Trial's spelling (its last one, when it lists the key twice)
  words            text NOT NULL,         -- its words: runs of a-z0-9 of the casefolded label, one space apart (search)
  PRIMARY KEY (nct_id, label_key)
);
CREATE INDEX trial_condition_by_key ON trial_condition (label_key);

CREATE TABLE criterion (                   -- immutable per (nct, eligibility_hash); old rows kept so old Verdicts resolve
  id               text PRIMARY KEY,      -- "{nct}:{hash8}:{ordinal}"
  nct_id           text NOT NULL REFERENCES trial(nct_id),
  eligibility_hash text NOT NULL,
  kind             text NOT NULL CHECK (kind IN ('inclusion','exclusion')),
  ordinal          int  NOT NULL,
  text             text NOT NULL
);
CREATE INDEX criterion_by_hash ON criterion (nct_id, eligibility_hash);

CREATE TABLE trial_site (                  -- the Trial's locations as last fetched; replaced with the trial row
  nct_id           text NOT NULL REFERENCES trial(nct_id),
  ordinal          int  NOT NULL,
  facility         text NOT NULL,
  city             text NOT NULL,
  country          text NOT NULL,
  status           text NOT NULL,         -- RECRUITING, NOT_YET_RECRUITING, ... ('' when the registry gives none)
  lat              double precision,      -- ClinicalTrials.gov geoPoint; NULL when the registry has none
  lon              double precision,
  PRIMARY KEY (nct_id, ordinal)
);

CREATE TABLE trial_contact (               -- who to contact about a Trial (#27); replaced with the trial row
  nct_id           text NOT NULL REFERENCES trial(nct_id),
  kind             text NOT NULL CHECK (kind IN ('sponsor','responsible_party','central','official','site')),
  site_ordinal     int  NOT NULL DEFAULT 0, -- trial_site.ordinal for kind 'site'; 0 otherwise
  ordinal          int  NOT NULL,
  name             text NOT NULL,
  role             text NOT NULL,         -- registry role: CONTACT, PRINCIPAL_INVESTIGATOR, SPONSOR, ... ('' if none)
  email            text NOT NULL,         -- '' when the registry gives none (likewise phone, affiliation, title)
  phone            text NOT NULL,
  affiliation      text NOT NULL,
  title            text NOT NULL,
  PRIMARY KEY (nct_id, kind, site_ordinal, ordinal)
);

CREATE TABLE trial_outcome (               -- a Trial's Outcomes (#25): planned outcome measures and posted results;
                                           -- replaced with the trial row
  nct_id           text NOT NULL REFERENCES trial(nct_id),
  kind             text NOT NULL CHECK (kind IN ('primary','secondary','other','result')),
  ordinal          int  NOT NULL,
  title            text NOT NULL,         -- the measure
  description      text NOT NULL,         -- '' when the registry gives none (likewise every text column below)
  time_frame       text NOT NULL,
  type             text NOT NULL,         -- kind 'result': PRIMARY, SECONDARY, OTHER_PRE_SPECIFIED, POST_HOC
  unit             text NOT NULL,         -- kind 'result': unit of measure
  param_type       text NOT NULL,         -- kind 'result': MEDIAN, MEAN, COUNT_OF_PARTICIPANTS, ...
  PRIMARY KEY (nct_id, kind, ordinal)
);

CREATE TABLE trial_outcome_value (         -- each group's value for a posted result (trial_outcome kind 'result')
  nct_id           text NOT NULL REFERENCES trial(nct_id),
  result_ordinal   int  NOT NULL,         -- trial_outcome.ordinal of the kind 'result' row
  ordinal          int  NOT NULL,
  group_title      text NOT NULL,         -- the arm or group
  label            text NOT NULL,         -- class and category titles when the measure is split
  value            text NOT NULL,
  spread           text NOT NULL,
  lower_limit      text NOT NULL,
  upper_limit      text NOT NULL,
  PRIMARY KEY (nct_id, result_ordinal, ordinal)
);

CREATE TABLE trial_publication (           -- publications the registry links to a Trial (#25); replaced with the trial row
  nct_id           text NOT NULL REFERENCES trial(nct_id),
  ordinal          int  NOT NULL,
  pmid             text NOT NULL,         -- PubMed id; '' when the registry gives only a citation
  type             text NOT NULL,         -- RESULT, BACKGROUND or DERIVED
  citation         text NOT NULL,
  PRIMARY KEY (nct_id, ordinal)
);

CREATE TABLE outcome_summary (            -- plain-language summary of a Closed trial's Outcomes (#26), written lazily
                                           -- on first open; immutable per (nct, Outcome content hash), old rows kept
  nct_id           text NOT NULL REFERENCES trial(nct_id),
  outcomes_hash    text NOT NULL,         -- sha256 of the Outcomes' canonical JSON it was written for
  summary          text NOT NULL,
  model            text NOT NULL,         -- the model that answered
  written_at       timestamptz NOT NULL,
  PRIMARY KEY (nct_id, outcomes_hash)
);

-- ---------- matching ----------
CREATE TABLE verdict (                     -- keyed by (Trial, eligibility hash, Profile version) per ADR 0002
  nct_id                 text NOT NULL REFERENCES trial(nct_id),
  eligibility_hash       text NOT NULL,   -- which Criteria set was judged; old-hash Verdicts are kept
  profile_version_id     text NOT NULL REFERENCES profile_version(id),
  outcome                text NOT NULL CHECK (outcome IN ('eligible','possible','excluded')),
  run_id                 text NOT NULL,
  attempts               int  NOT NULL,
  unsupported_downgraded int  NOT NULL DEFAULT 0,
  degraded               boolean NOT NULL DEFAULT false,   -- loop hit its bound; unsupported claims became unknown
  created_at             timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (nct_id, eligibility_hash, profile_version_id)
);

CREATE TABLE criterion_result (
  nct_id             text NOT NULL,
  eligibility_hash   text NOT NULL,
  profile_version_id text NOT NULL,
  criterion_id       text NOT NULL REFERENCES criterion(id),
  outcome            text NOT NULL CHECK (outcome IN ('met','not_met','unknown')),
  fact_id            text REFERENCES fact(id),
  rationale          text NOT NULL,
  ask                text,                 -- unknown only: questionnaire question ("Q8") for a Respondent question
  PRIMARY KEY (nct_id, eligibility_hash, profile_version_id, criterion_id),
  FOREIGN KEY (nct_id, eligibility_hash, profile_version_id) REFERENCES verdict ON DELETE CASCADE,
  CHECK ((outcome = 'unknown') = (fact_id IS NULL))     -- the evaluator invariant, also in the DB
);

CREATE TABLE doctor_question (
  nct_id             text NOT NULL,
  eligibility_hash   text NOT NULL,
  profile_version_id text NOT NULL,
  criterion_id       text NOT NULL REFERENCES criterion(id),
  subject            text NOT NULL,
  text               text NOT NULL,
  PRIMARY KEY (nct_id, eligibility_hash, profile_version_id, criterion_id),
  FOREIGN KEY (nct_id, eligibility_hash, profile_version_id) REFERENCES verdict ON DELETE CASCADE
);

CREATE TABLE respondent_question (       -- an unknown raises this OR a doctor_question, never both
  nct_id             text NOT NULL,
  eligibility_hash   text NOT NULL,
  profile_version_id text NOT NULL,
  criterion_id       text NOT NULL REFERENCES criterion(id),
  question_id        text NOT NULL,        -- questionnaire question id, "treatments"
  question           text NOT NULL,        -- its number, "Q8"
  subject            text NOT NULL,        -- its wording
  text               text NOT NULL,
  PRIMARY KEY (nct_id, eligibility_hash, profile_version_id, criterion_id),
  FOREIGN KEY (nct_id, eligibility_hash, profile_version_id) REFERENCES verdict ON DELETE CASCADE
);

-- ---------- World Model engine log (engine-owned) ----------
CREATE TABLE wm_event (
  namespace  text   NOT NULL,
  seq        bigint NOT NULL,              -- monotonic per namespace, by append order
  id         text   NOT NULL UNIQUE,       -- stable id; duplicate append after a crash is rejected
  kind       text   NOT NULL,              -- upsertEntity | upsertContext | relate | assertFact | snapshot | ...
  payload    jsonb  NOT NULL,              -- carries provenance (kind, at, checksum, url, run_id)
  at         text   NOT NULL,              -- observation time from provenance, never the wall clock
  PRIMARY KEY (namespace, seq)
);

CREATE TABLE wm_audit (
  namespace  text   NOT NULL,
  seq        bigint NOT NULL,
  at         text   NOT NULL,
  kind       text   NOT NULL,
  actor      text   NOT NULL,
  summary    text   NOT NULL,
  event_id   text   REFERENCES wm_event(id),
  run_id     text,
  PRIMARY KEY (namespace, seq)
);

-- ---------- trace (app.trace) ----------
CREATE TABLE trace_run (
  id             text PRIMARY KEY,
  kind           text NOT NULL CHECK (kind IN ('ingest','rescan')),
  correlation_id text NOT NULL,           -- the run the user started; an ingest and its Re-scan share it
  patient_id     text REFERENCES patient(id),
  document_hash  text,                    -- ingest runs; for the awaiting-patient lookup
  created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX trace_run_by_document ON trace_run (document_hash);
CREATE INDEX trace_run_by_correlation ON trace_run (correlation_id);

CREATE TABLE trace_event (
  event_id      text PRIMARY KEY,         -- uuid5(actor, cause, index): duplicate appends are ignored
  run_id        text NOT NULL REFERENCES trace_run(id),
  seq           bigserial NOT NULL,       -- allocated by the DB, so parallel Matcher tasks can append
  kind          text NOT NULL,
  actor         text NOT NULL,
  causation_id  text REFERENCES trace_event(event_id),
  llm_call_ids  text[] NOT NULL DEFAULT '{}',
  payload       jsonb NOT NULL,
  at            timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX trace_event_by_run ON trace_event (run_id, seq);

CREATE TABLE llm_call (
  id                text PRIMARY KEY,
  run_id            text REFERENCES trace_run(id),
  lane              text NOT NULL,
  model_requested   text NOT NULL,
  model_answered    text NOT NULL,        -- what Nightshift actually used; shown in the trace
  prompt_tokens     int  NOT NULL,
  completion_tokens int  NOT NULL,
  latency_ms        int  NOT NULL,
  ok                boolean NOT NULL,
  at                timestamptz NOT NULL DEFAULT now()
);
