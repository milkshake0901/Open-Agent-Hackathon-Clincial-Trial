"""Fetch recruiting trials and judge them against a parsed letter.

    doppler run -- backend/.venv/bin/python backend/scripts/screen_referral.py

The search is the condition and the place. Prior drugs are not required search terms.
Each decisive criterion names a region of the letter.
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

import asyncpg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings  # noqa: E402
from app.ctx import Ctx  # noqa: E402
from app.extraction import NemotronParse  # noqa: E402
from app.llm.nightshift import Nightshift  # noqa: E402
from app.matching import screen_letter  # noqa: E402
from app.sql.reader import PgReader  # noqa: E402
from app.sql.writer import PgWriter  # noqa: E402
from app.trials import sync  # noqa: E402
from app.worldmodel import PgEventStore, WorldModel  # noqa: E402

CONDITION = "metastatic castration-resistant prostate cancer"
LOCATION = "United Kingdom"
PATIENT_ID = "pt_referral_20260209"
MAX_TRIALS = 20
SCREEN = 5


async def main() -> int:
    settings = Settings()
    pool = await asyncpg.create_pool(settings.pg_dsn, min_size=1, max_size=4)
    writer = PgWriter(pool)
    reader = PgReader(pool)
    wm = WorldModel(namespace="trialmatch", store=PgEventStore(writer, "trialmatch"))
    await wm.replay()
    llm = Nightshift(settings.meterless_base_url, settings.meterless_runtime_token, settings.meterless_app_id,
                     settings.lane_models, default_model=settings.meterless_model)
    ctx = Ctx(writer=writer, agent_reader=reader, ui_reader=reader, llm=llm, parser=NemotronParse(settings), wm=wm,
              settings=settings, now=lambda: datetime.now(timezone.utc))
    try:
        report = await sync(ctx, CONDITION, LOCATION, max_trials=MAX_TRIALS)
        nct_ids = list(report.new + report.changed + report.unchanged)[:SCREEN]
        print(f"fetched {report.fetched} from {report.source}; screening {len(nct_ids)}")
        screens = await screen_letter(ctx, PATIENT_ID, nct_ids)
    finally:
        await llm.aclose()
        await pool.close()
    for screen in screens:
        print(f"\n{screen.outcome.upper()}  {screen.nct_id}  {screen.title}")
        for row in screen.criteria:
            if row.outcome == "unknown":
                continue
            print(f"  {row.outcome} {row.kind} p{row.page}: {row.quote}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
