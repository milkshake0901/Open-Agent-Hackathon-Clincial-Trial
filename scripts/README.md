# Scripts

- `meterless.py` checks the Nightshift connection: status, Auto Detect, chat, a lane's JSON call, media plan and `illustrate`. Usage in DEVELOPER.md, "Check the LLM connection yourself".
- `ingest_trials.py --pages <dir>` runs the Australia-wide ingest (`trials.ingest`, ADR 0004) from saved ClinicalTrials.gov v2 study pages and prints new / changed / unchanged counts. Safe to re-run; no model calls, no Re-scan.

To be written:


- `seed_demo.py` registers the demo patient and uploads `data/demo/` Documents in story order.
- `sync_trials.py` calls `trials.sync`; schedule it daily with cron or launchd.
- `rebuild_projections.py` truncates the projected tables and replays `wm_event`, proving they are derived from the World Model.
