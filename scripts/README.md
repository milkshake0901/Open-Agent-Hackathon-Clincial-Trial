# Scripts

- `meterless.py` checks the Nightshift connection: status, Auto Detect, chat, a lane's JSON call, media plan and `illustrate`. Usage in DEVELOPER.md, "Check the LLM connection yourself".
- `ingest_trials.py --live` (or `--pages <dir>`) runs the Australia-wide ingest (`trials.ingest`, ADR 0004) from the live ClinicalTrials.gov v2 API (or saved study pages) and prints new / changed / unchanged / Closed / dropped counts. Safe to re-run (it also drops stored Trials that aged past 15 years, were withdrawn or lost every Australian site); no model calls, no Re-scan.
- `rebuild_projections.py` truncates the projected tables and replays `wm_event`, proving they are derived from the World Model (ADR 0001). One transaction; safe to re-run.

To be written:


- `seed_demo.py` registers the demo patient and uploads `data/demo/` Documents in story order.
- `sync_trials.py` calls `trials.sync`; schedule it daily with cron or launchd.
