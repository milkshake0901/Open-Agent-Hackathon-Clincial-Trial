# Ingest every Australian ClinicalTrials.gov study; judge only Open trials

Status: accepted, 2026-10-25.

We replace the per-condition `trials.sync` with a one-off, re-runnable bulk ingest of every ClinicalTrials.gov study that has at least one Trial site in Australia. It is written as World Model events and read by agents through Zetaris, as ADR 0001 requires; the Zetaris REST table is one fixed URL and cannot page through thousands of studies. Only Australian sites are kept. Withdrawn studies are dropped, and Closed trials are kept only if they finished within 15 years of the ingest date (primary completion date, falling back to completion date, then last update).

Open trials (recruiting, not yet recruiting, enrolling by invitation) are judged as before. Closed trials are selected by Condition term only and get no Criterion results or Verdict, because eligibility means nothing for a study that cannot enrol. They are shown for their Outcomes (outcome measures, posted results, publications) and contacts.

We chose this over ingesting per patient condition because patients should be able to browse related past research. We also chose it over judging everything, because LLM work at ingest would cost the most on conditions no patient has. So the ingest stores only eligibility text and its hash; Criteria are split, and Outcome summaries written, lazily when a patient first needs them.

ANZCTR is out of scope for now: adding it changes what identifies a Trial (ACTRN as well as NCT IDs, plus de-duplication) and needs its own decision.

## Consequences

- The ingest never triggers a Re-scan or any LLM call; new Open trials are judged at the next requested Re-scan.
- A Trial that closes between ingests keeps its earlier Verdicts (ADR 0002), is marked no longer recruiting, and from then on is shown as a Closed trial and never re-judged.
- Enquiries are drafted for the Respondent to edit, copy and send themselves. The app never sends them and does not store them, and the model sees only de-identified details; name and contact are placeholders filled on the Respondent's side.
- Re-running the ingest is idempotent on NCT ID and eligibility hash, and it also drops Closed trials that have aged past 15 years.
- Any status that is neither Open nor Closed (withdrawn, and the expanded access statuses such as available or no longer available) is not stored: expanded access is neither joinable nor research to learn from. A Trial stored by an earlier run that is now in such a status, or lists no Australian site, is dropped the same way as an aged-out Closed trial: no longer listed or judged, its Verdicts kept as history.
