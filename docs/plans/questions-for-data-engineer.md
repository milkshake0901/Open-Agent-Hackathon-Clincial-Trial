# Questions for the data engineer

TrialMatch matches a patient's clinical Documents against ClinicalTrials.gov eligibility. Agents read only through Zetaris; our own Postgres holds the data (ADR 0001). Below are the questions we can't answer from the docs. The first five block the build, so please answer those first.

Fill in each **Answer** line. Background: [README.md](../../README.md), [docs/architecture.md](../architecture.md), [ADR 0001](../adr/0001-write-postgres-read-through-zetaris.md).

## Blocking (needed in the next day)

### 1. Does Lightning SQL accept our query style?
Our query functions in `backend/app/sql/reader.py` use array parameters (`WHERE nct_id = ANY(:ids)`), window functions (`ROW_NUMBER() OVER (PARTITION BY ... ORDER BY observed_on DESC)`) and CTEs. Does Lightning SQL run these against a registered Postgres source, or will we have to rewrite them?

**Answer:**

### 2. Does Zetaris cache reads from a registered Postgres, and for how long?
The World Model writes a Fact to Postgres, and an agent then reads it through Zetaris straight away. We need to know how long to wait before the agent can see the write. Can caching be turned off per table, or the cache refreshed on demand?

**Answer:**

### 3. Can Zetaris page through a REST source?
ClinicalTrials.gov v2 returns pages linked by `nextPageToken`. Is one `CREATE LIGHTNING REST TABLE` always one page? If so, is there a supported way to pull every page, or should we fall back to direct HTTP for the fetch and only register the stored result?

**Answer:**

### 4. How does a REST table handle sparse, deeply nested JSON?
Trial records have nested structs (`protocolSection.eligibilityModule.*`), lists of structs (`locations` with `geoPoint`, `interventions`) and fields that many studies leave empty. Is the schema inferred from the first page only? What happens to a field that is missing from that page but present later?

**Answer:**

### 5. Are long text fields truncated?
`eligibilityCriteria` can run to more than 10,000 characters. Does a REST table or a SCHEMASTORE view truncate long strings, and is there a limit we should know about?

**Answer:**

## Data model and registration

### 6. Which is better: registering our Postgres tables individually, or registering the whole database?
`db/zetaris_register.sql` registers our Postgres container (port 5433) as a source. Is there a recommended way to expose only the domain tables (fact, profile_version, trial, criterion, verdict, criterion_result, doctor_question) and keep `wm_event` and `trace_*` hidden from agents?

**Answer:**

### 7. Can one SQL query join our Postgres with the ClinicalTrials.gov REST table?
For example, joining the patient's Facts with live trial eligibility in one statement. Does that work in practice, and how fast is it with about 10 trials?

**Answer:**

### 8. Should we use the Unified Semantic Layer?
Would defining a semantic view (for example "current patient profile" and "active trials") help the agents, or is plain SQL against the registered tables enough for a hackathon demo?

**Answer:**

### 9. How do we pass parameters safely over the REST API?
Agents send SQL to `POST /sql-editor/sqls/run`. Is there parameter binding, or do we have to build SQL strings ourselves (and escape them)?

**Answer:**

## Privacy and local-first

### 10. Does anything leave the machine?
With Zetaris running locally in Docker, does any query text, result or telemetry go to Zetaris Cloud? Our data includes de-identified patient Facts.

**Answer:**

### 11. Can source PDFs stay out of Zetaris completely?
We plan to store only extracted Facts (with Document hash and page number) and never the PDFs. Is there any Zetaris feature that would need the files themselves (for example the ai-datasteward service)?

**Answer:**

## Operations

### 12. What does the REST API return for an error?
Status codes and body format for a bad query, a timeout, and a source that can't be reached. We want agents to tell a failed query apart from an empty result.

**Answer:**

### 13. How many queries at once can a local instance handle?
A Re-scan can run several agent reads in parallel. Is there a limit before queries queue or fail with the laptop settings in the guide (`local[2]`, 2 GB driver memory)?

**Answer:**

### 14. How do we reset cleanly between demo runs?
Without `docker compose down -v`, which deletes encryption keys. Is dropping and re-creating our registered sources enough?

**Answer:**

### 15. Is there a recommended way to see what each query cost?
For the trace panel in our demo: query time, rows scanned, which source answered. Does the REST response include any of this?

**Answer:**
