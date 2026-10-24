# One-Trial Zetaris test (NCT07680790)

This test proves the whole path on one Trial before anyone scales it to a cohort:

```
CT.gov API v2 ──REST table──▶ Zetaris views (ctgov.*) ──load_criteria.py──▶ Postgres criterion
                                                                               │ (datasource trialmatch)
                                   trialmatch_mart ◀── criterion_topic view ◀──┘
```

**Status 2026-10-24: every step ran and matched its expected values.** The `trialmatch` datasource was registered
through the UI (Create Database Source, JDBC URL `jdbc:postgresql://host.docker.internal:5433/trialmatch`), not with
the SQL in `db/zetaris_register.sql`. The keys live in the repo's `.env`, so pass `--env-file .env` to `run_sql.py`.

## Prerequisites (do these yourself)
1. Create a Zetaris API key in the local UI, then add these lines to `.env.local` at the repo root:
   - `ZETARIS_API_KEY` (the new key)
   - `ZETARIS_REST_URL=http://localhost:8888/api/v1.0`
   - `ZETARIS_USER_AGENT="trialmatch you@example.org"` (an app name followed by your contact email)
2. Start the database with `docker compose up -d postgres`. Its first start loads `db/schema.sql` through
   `docker-entrypoint-initdb.d`, so don't apply the schema again.

## Run order (from the repo root)
| # | What | Command |
|---|---|---|
| 1 | Register the CT.gov REST table and create the `ctgov` views | `python3 .scratch/ctgov-discovery/ref/run_sql.py .scratch/zetaris-one-trial/01_ctgov_one_trial.sql` |
| 2 | Register our Postgres as datasource `trialmatch` | run section 1 of `db/zetaris_register.sql` in the SQL Editor |
| 3 | Read the Trial through Zetaris, split it into Criteria, write Postgres | `backend/.venv/bin/python .scratch/zetaris-one-trial/load_criteria.py` |
| 3b | Check it through Zetaris: expect `8`, with 4 inclusion and 4 exclusion | `SELECT kind, COUNT(*) FROM trialmatch.criterion WHERE nct_id = 'NCT07680790' GROUP BY kind;` |
| 4 | Create the topic view | `python3 .scratch/zetaris-one-trial/gen_topic_view.py`, then `run_sql.py …/02_criterion_topic.sql` |
| 5 | Build the data mart | SQL below |

After each statement, fill in its `OUTCOME:` line in the SQL files. Each one lists the expected values.

## Step 5: data mart (`trialmatch_mart`)
Run `03_datamart.sql`. Its syntax worked on 2026-10-24. `DESCRIBE BY` accepts only letters, digits, spaces and
`_ . - ,`; a `:` or `+` gets HTTP 400 "Description is invalid".

```sql
CREATE DATAMART trialmatch_mart DESCRIBE BY 'TrialMatch: patient Facts + CT.gov Trials + Criterion topics';
ADD DATAMART TABLE trial_core     INTO trialmatch_mart FROM ctgov.ctgov_trial_core
  VSCHEMA (nct_id nct_id, title title, overall_status overall_status, last_update_posted last_update_posted,
           conditions conditions, sex sex,
           minimum_age minimum_age, healthy_volunteers healthy_volunteers, eligibility_text eligibility_text,
           eligibility_len eligibility_len);
ADD DATAMART TABLE trial_sites    INTO trialmatch_mart FROM ctgov.ctgov_trial_sites
  VSCHEMA (nct_id nct_id, facility facility, city city, state state, country country, site_status site_status,
           lat lat, lon lon);
ADD DATAMART TABLE trial_mesh     INTO trialmatch_mart FROM ctgov.ctgov_trial_mesh
  VSCHEMA (nct_id nct_id, mesh_id mesh_id, mesh_term mesh_term);
ADD DATAMART TABLE criterion      INTO trialmatch_mart FROM trialmatch.criterion
  VSCHEMA (id id, nct_id nct_id, eligibility_hash eligibility_hash, kind kind, ordinal ordinal, text text);
ADD DATAMART TABLE criterion_topic INTO trialmatch_mart FROM trialmatch_views.criterion_topic
  VSCHEMA (criterion_id criterion_id, nct_id nct_id, eligibility_hash eligibility_hash, kind kind, ordinal ordinal,
           topic topic);
ADD DATAMART TABLE fact           INTO trialmatch_mart FROM trialmatch.fact
  VSCHEMA (id id, document_hash document_hash, page page, resource resource, subject subject, value value,
           unit unit, observed_on observed_on, quote quote, created_at created_at);
```

## Pass check: one statement across both sources
**Query A (recruiting sites):** expect Criterion 4, "ECOG Performance Status 0-1", once for each of the
5 RECRUITING sites (none of them is in Sydney yet).

```sql
SELECT c.ordinal, c.text, s.facility, s.city, s.country
FROM trialmatch_mart.criterion_topic t
JOIN trialmatch_mart.criterion   c ON c.id = t.criterion_id
JOIN trialmatch_mart.trial_sites s ON s.nct_id = c.nct_id
WHERE t.topic = 'performance_status' AND s.site_status = 'RECRUITING';
```

**Query B (sites near Sydney):** expect the same Criterion once for each of the two Sydney-area sites, both
NOT_YET_RECRUITING (3.8 km and 21.7 km). Run it twice. About a second on the second run means it read the cache
and did not call CT.gov again.

```sql
SELECT c.ordinal, c.text, s.facility, s.site_status
FROM trialmatch_mart.criterion_topic t
JOIN trialmatch_mart.criterion   c ON c.id = t.criterion_id
JOIN trialmatch_mart.trial_sites s ON s.nct_id = c.nct_id
WHERE t.topic = 'performance_status'
  AND s.lat IS NOT NULL
  AND 6371 * 2 * asin(sqrt(pow(sin(radians(s.lat + 33.8688) / 2), 2)
      + cos(radians(-33.8688)) * cos(radians(s.lat)) * pow(sin(radians(s.lon - 151.2093) / 2), 2))) <= 50;
```

`fact` is in the mart but empty until the patient side lands. Once it has rows, the matcher's ECOG check becomes this
same query joined to `fact` on `subject = 'ECOG'`.

## Known gaps
- `load_criteria.py` writes Postgres directly, not through the World Model (ADR 0001), because `record_trials` isn't implemented yet.
- What Postgres should keep vs read live is an open question for the data engineer: `docs/plans/zetaris-trial-storage-question.md`.
- `ctgov-discovery/scripts/05_zetaris_probe.sql` uses the User-Agent `trialmatch-discovery YOUR_CONTACT_EMAIL`, which
  `run_sql.py` won't replace, because it only swaps the exact placeholder `YOUR_APP_NAME YOUR_CONTACT_EMAIL`.
