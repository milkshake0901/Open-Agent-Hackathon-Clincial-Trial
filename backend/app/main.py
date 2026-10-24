"""app/main.py — FastAPI app. The lifespan builds one Ctx: Postgres pool and writer, PgReader (UI),
ZetarisReader (agents), the Nightshift client, and the World Model with PgEventStore (replayed from wm_event)."""
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import asyncpg
from fastapi import FastAPI

from app import trials
from app.api import EXCEPTION_HANDLERS, router
from app.config import Settings
from app.ctx import Ctx
from app.llm.nightshift import Nightshift
from app.sql.reader import PgReader
from app.sql.writer import PgWriter
from app.worldmodel import PgEventStore, WorldModel

WORLD_MODEL_NAMESPACE = "trialmatch"


@asynccontextmanager
async def lifespan(app: FastAPI):
    if getattr(app.state, "ctx", None) is not None:   # tests install their own Ctx
        yield
        return
    settings = Settings()
    pool = await asyncpg.create_pool(settings.pg_dsn, min_size=1, max_size=8)
    writer = PgWriter(pool)
    reader = PgReader(pool)
    wm = WorldModel(namespace=WORLD_MODEL_NAMESPACE, store=PgEventStore(writer, WORLD_MODEL_NAMESPACE))
    await wm.replay()
    llm = Nightshift(settings.meterless_base_url, settings.meterless_runtime_token, settings.meterless_app_id,
                     settings.lane_models, default_model=settings.meterless_model)
    await llm.models()   # warns, never fails: a missing runtime turns model calls into LlmUnavailable
    # Until ZetarisReader lands, agents read Postgres directly.
    app.state.ctx = Ctx(writer=writer, agent_reader=reader, ui_reader=reader, llm=llm, wm=wm,
                        settings=settings, now=lambda: datetime.now(timezone.utc))
    # Trials come from the saved snapshot until live sync (Zetaris) lands; idempotent across restarts.
    await trials.load_snapshot(app.state.ctx, settings.trials_snapshot_dir)
    try:
        yield
    finally:
        await llm.aclose()
        await pool.close()


app = FastAPI(title="TrialMatch", lifespan=lifespan, exception_handlers=EXCEPTION_HANDLERS)
app.include_router(router)
