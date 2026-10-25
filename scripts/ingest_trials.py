"""Run the Australia-wide ClinicalTrials.gov ingest (ADR 0004) into the Trial cache. Reads the repo's .env.

    backend/.venv/bin/python scripts/ingest_trials.py --pages <dir>   # saved GET /api/v2/studies pages, one per file

Safe to re-run: unchanged studies record nothing. Makes no model call and starts no Re-scan.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import asyncpg  # noqa: E402

from app import trials  # noqa: E402
from app.config import Settings  # noqa: E402
from app.ctx import Ctx  # noqa: E402
from app.llm.nightshift import Nightshift  # noqa: E402
from app.main import WORLD_MODEL_NAMESPACE  # noqa: E402
from app.sql.reader import PgReader  # noqa: E402
from app.sql.writer import PgWriter  # noqa: E402
from app.worldmodel import PgEventStore, WorldModel  # noqa: E402


async def main(args: argparse.Namespace) -> int:
    s = Settings(_env_file=ROOT / ".env")
    pool = await asyncpg.create_pool(s.pg_dsn, min_size=1, max_size=4)
    writer, reader = PgWriter(pool), PgReader(pool)
    wm = WorldModel(namespace=WORLD_MODEL_NAMESPACE, store=PgEventStore(writer, WORLD_MODEL_NAMESPACE))
    await wm.replay()
    # The ingest never calls a model; the client is only there because every Ctx carries one.
    llm = Nightshift(s.meterless_base_url, s.meterless_runtime_token, s.meterless_app_id, s.lane_models,
                     default_model=s.meterless_model)
    ctx = Ctx(writer=writer, agent_reader=reader, ui_reader=reader, llm=llm, wm=wm, settings=s,
              now=lambda: datetime.now(timezone.utc))
    try:
        report = await trials.ingest(ctx, trials.SavedPages(Path(args.pages)))
    finally:
        await llm.aclose()
        await pool.close()
    print(f"{report.fetched} Trials from {report.source}: {len(report.new)} new, {len(report.changed)} changed, "
          f"{len(report.unchanged)} unchanged")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pages", required=True, help="directory of saved ClinicalTrials.gov v2 study pages")
    sys.exit(asyncio.run(main(parser.parse_args())))
