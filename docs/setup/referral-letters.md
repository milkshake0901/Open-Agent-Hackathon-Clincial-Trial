# Referral letters and trial questions

A referral letter or report added on the home page is read into Regions. On the Trials page each recruiting trial takes a free-form question about it, for any condition. Zetaris reads the trial criteria and the patient's Regions. The model answers from those words and has to cite a Region that is actually in one of the patient's documents.

The answer is not saved and never changes a Verdict. The Matcher still judges Facts through the usual Re-scan once a Condition term is ticked.

## What you can do in the app

The frontend is `http://localhost:3001`. The API is `http://127.0.0.1:8000`.

**Home (`/`).** "Start from a referral letter" takes a PDF and adds it to the Respondent's own record, like "Add documents": it is read page by page into Regions, and the Intake agent drafts its Facts in the background, each citing the Region it quotes. Until the short questionnaire lands (#49) it also fills who is answering, sex, when diagnosed, the diagnosis, treatments and medicines now from the letter. Check the fields, then save.

**Trials (`/trials?patient=<id>&version=<id>`).** Opened from the home page once the answers are saved and the diagnosis step is done. Under each recruiting trial, **Ask a question of this trial** opens the question:

- **Am I eligible?** and **What should I gather before applying?** send that question.
- The box under them sends whatever you type. One trial at a time. A call is often about 40 seconds and can fail around 60 seconds if Nightshift returns `502 Load failed`.
- **Exclusion criteria your documents show** lists an exclusion only when two things are true: the quoted line is copied from that trial's stored exclusion, and the Region it names is real. A line the model invents is dropped.
- **Where your documents say this** lists each cited Region. Clicking one, or an exclusion line, opens the side panel with that page and every cited Region on it boxed.

The question needs at least one document read into Regions; without one the page asks you to add a letter or report first.

## How a question is answered

1. Zetaris reads the trial, its criteria, and this patient's `document_span` rows (`ctx.agent_reader`). The page image is read from Postgres, and the PDF bytes never go to Zetaris.
2. One Nightshift call on the deep lane (Nemotron 3 Ultra) sees the question, the criteria, and the patient's Regions of the kinds Intake reads: Text, Title, Section-header, List-item, Table and Caption. Page headers, page footers and pictures are letterhead, never shown. A structured report's findings are often List-items or a Table.
3. The reply is checked in code. A Region id that is not one of the patient's Regions is dropped. An exclusion is kept only when its clause is a verbatim excerpt of the stored criterion and its region is real. A firm eligible or excluded answer with no real region becomes "More information is needed".

`fact.span_id` is set for a Fact Intake read from a letter's Region. Questionnaire Facts leave it null. The trial question reads the Regions directly. It does not wait for Intake to commit Facts.

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

To parse one PDF from the command line instead of the form (for `screen_referral.py`, which reads that patient):

```bash
doppler run --project open-agent-hackathon --config dev_personal -- \
  backend/.venv/bin/python backend/scripts/load_referral.py path/to/referral.pdf
```

That script stores the letter on patient `pt_referral_20260209`. The form upload adds it to the Respondent's own patient instead. The PDF is kept under `data/raw/`, which is gitignored. Do not commit it.

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
| Fill questionnaire fields from regions (until #49) | `backend/app/record/prefill.py`, `POST /api/patients/{id}/referral/prefill` |
| One question about one trial | `backend/app/matching/letter.py` `ask_trial`, `POST /api/patients/{id}/trials/{nct}/ask`, `frontend/src/app/trials/trial-question.tsx` |
| Page image and boxes | `GET /api/documents/{hash}/pages/{n}/image`, `GET /api/documents/{hash}/regions`, `frontend/src/app/region-page.tsx` |
