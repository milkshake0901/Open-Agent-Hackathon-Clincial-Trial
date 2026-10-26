"""Rebuild every projected table (fact, profile_version, trial, trial_outcome, verdict, ...) from wm_event alone
(ADR 0001), proving they are derived from the World Model. Reads the repo's .env.

    backend/.venv/bin/python backend/scripts/rebuild_projections.py

Truncates the projected tables and replays the event log through the projector in one transaction, so a failure
leaves them as they were. Safe to re-run. Makes no model call.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import asyncpg  # noqa: E402

from app.config import REPO_ROOT, Settings  # noqa: E402
from app.main import WORLD_MODEL_NAMESPACE  # noqa: E402
from app.sql.writer import PgWriter  # noqa: E402
from app.worldmodel import rebuild_projections  # noqa: E402


async def main() -> int:
    s = Settings(_env_file=REPO_ROOT / ".env")
    pool = await asyncpg.create_pool(s.pg_dsn, min_size=1, max_size=2)
    try:
        replayed = await rebuild_projections(PgWriter(pool), WORLD_MODEL_NAMESPACE)
    finally:
        await pool.close()
    print(f"Rebuilt the projected tables from {replayed} World Model events ({WORLD_MODEL_NAMESPACE})")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
