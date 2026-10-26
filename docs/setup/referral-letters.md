# Referral letters and trial questions

A scanned referral can fill the home questionnaire, and the record page can ask one stored Australian trial a question against that letter. Zetaris reads the trial criteria and the letter regions. The model answers from those words and has to cite a region that is actually on the letter.

This does not save a Verdict. The Matcher still judges Facts through the usual Re-scan once a Condition term is ticked.

## What you can do in the app

The frontend is `http://localhost:3001`. The API is `http://127.0.0.1:8000`.

**Home (`/`).** "Start from a referral letter" takes a PDF. "Fill answers from this letter" parses it and fills who is answering, sex, when diagnosed, the diagnosis, treatments, and medicines now. Birth month, postcode, travel, allergies, and contact stay blank. Check the fields, then save. Saving still runs Intake and can take a few minutes; the bar on the button is only a clock. A letter already parsed is listed under "Already read" and fills the form without parsing again.

**Record (`/record`).** This lists stored Australian trials whose condition name matches metastatic castration-resistant prostate cancer, including the short form mCRPC. Open trials are still taking people. Past trials are under the disclosure. On each open trial:

- **Am I eligible?** and **What should I gather before applying?** send that question.
- The box under them sends whatever you type. One trial at a time. A call is often about 40 seconds and can fail around 60 seconds if Nightshift returns `502 Load failed`.
- **Exclusion criteria the letter shows** lists an exclusion only when two things are true: the quoted line is copied from that trial's stored exclusion, and the letter region it names is real. A line the model invents is dropped.
- **Show on the letter** loads the page image and draws a box on each cited region. Clicking an exclusion line opens that page.

The record page uses patient `pt_referral_20260209` unless the URL is `/record?patient=<id>`.

## How a question is answered

1. Zetaris reads the trial, its criteria, and this patient's `document_span` rows (`ctx.agent_reader`). The page image is read from Postgres, and the PDF bytes never go to Zetaris.
2. One Nightshift call on the deep lane (Nemotron 3 Ultra) sees the question, the criteria, and the letter's Text regions.
3. The reply is checked in code. A region id that is not on the letter is dropped. An exclusion is kept only when its clause is a verbatim excerpt of the stored criterion and its region is real. A firm eligible or excluded answer with no real region becomes "More information is needed".
4. A clock tool measures washouts. When an exclusion says a treatment must not have been given within N days, weeks, or months, the tool reads the dates on the letter and subtracts them from today. If the latest date is outside that window, that exclusion is not listed. The page shows the date, the number of days, and the window. An exclusion with no time window is left as written.

`fact.span_id` is there for a Fact that quotes a region. Questionnaire Facts leave it null. The trial question reads the regions directly. It does not wait for Intake to commit Facts.

## Run it

Postgres, Zetaris, and Nightshift need to be up. From the repo root, with the venv already installed (`DEVELOPER.md`):

```bash
docker compose up -d
# API. The keys have to be in the environment. Either .env (see .env.example) or Doppler, below.
doppler run --project open-agent-hackathon --config dev_personal -- \
  backend/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In another shell:

```bash
cd frontend && npm install && npm run dev
```

There is no `--reload`. Restart the API after a schema or code change. Restart it after `REGISTER DATASOURCE TABLES` as well: column types are read once at startup.

To parse one PDF from the command line instead of the form:

```bash
doppler run --project open-agent-hackathon --config dev_personal -- \
  backend/.venv/bin/python scripts/load_referral.py path/to/referral.pdf
```

That script stores the letter on patient `pt_referral_20260209`. The form upload gives a new patient id from the file bytes. The PDF is kept under `data/raw/`, which is gitignored. Do not commit it.

## Doppler

Project `open-agent-hackathon`. This repo is linked to config `dev_personal` (`doppler configure` from the repo root).

| Secret | Who needs it |
|---|---|
| `METERLESS_BASE_URL`, `METERLESS_RUNTIME_TOKEN`, `METERLESS_MODEL` | Nightshift. Already on the shared `dev` config. |
| `ZETARIS_API_KEY` | Agent reads. Without it the API logs a warning and agents read Postgres. |
| `NVIDIA_PARSE_API_KEY` | Nemotron Parse (`nvidia/nemotron-parse`) for a scanned letter. This is not `NVIDIA_BUILD_SECRET`. |

`ZETARIS_API_KEY` and `NVIDIA_PARSE_API_KEY` are on `dev_personal`, not on the shared `dev` config. Copy them into your own Doppler config, or put the same names in `.env`. Never commit either value.

The other Zetaris settings have defaults: `ZETARIS_REST_URL=http://localhost:8888/api/v1.0`, `ZETARIS_ORG_ID=1`, `ZETARIS_DATASOURCE=trialmatch`.

## Database

The Australia snapshot is a custom-format dump. Restoring it replaces the trial rows. It does not include `document_span`, and a database created before that table is missing `fact.span_id`. After a restore, from the repo root:

```bash
docker compose cp db/migrate_document_span.sql postgres:/tmp/migrate_document_span.sql
docker compose exec postgres psql -U trialmatch -d trialmatch -f /tmp/migrate_document_span.sql
```

A fresh volume that ran current `db/schema.sql` already has the table. The migration is safe to run again.

Then register the tables in Zetaris, one statement at a time. `db/zetaris_register.sql` is the source. The description cannot contain parentheses; the file uses `TrialMatch Postgres, World Model projections`. If the datasource already exists, run only:

```sql
REGISTER DATASOURCE TABLES FROM trialmatch
```

Re-run that after any new table or column. `document_span` has to be visible or a trial question fails with `TABLE_OR_VIEW_NOT_FOUND`.

## Code

| Piece | Where |
|---|---|
| Parse a PDF into regions | `backend/app/extraction/parse.py` |
| Store the letter and its regions | `backend/app/record/referral.py` |
| Fill questionnaire fields from regions | `backend/app/record/prefill.py`, `POST /api/referrals` |
| Stored mCRPC list | `GET /api/trials/matching` |
| One question about one trial | `backend/app/matching/letter.py` `ask_trial`, `POST /api/patients/{id}/trials/{nct}/ask` |
| Page image and boxes | `GET /api/documents/{hash}/pages/{n}/image`, `frontend/src/app/record/matching.tsx` |
