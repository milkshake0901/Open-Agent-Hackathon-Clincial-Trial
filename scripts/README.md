# Scripts

- `meterless.py` checks the Nightshift connection: status, Auto Detect, chat, a lane's JSON call, media plan and `illustrate`. Usage in DEVELOPER.md, "Check the LLM connection yourself".

To be written:


- `seed_demo.py` registers the demo patient and uploads `data/demo/` Documents in story order.
- `sync_trials.py` calls `trials.sync`; schedule it daily with cron or launchd.
- `rebuild_projections.py` truncates the projected tables and replays `wm_event`, proving they are derived from the World Model.
