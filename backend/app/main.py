"""app/main.py — FastAPI app. The lifespan builds one Ctx: Postgres pool and writer, PgReader (UI),
ZetarisReader (agents), the Nightshift client, and the World Model with PgEventStore (replayed from wm_event)."""
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import asyncpg
from fastapi import FastAPI

from app.api import router
from app.config import Settings
from app.ctx import Ctx
from app.llm.nightshift import FakeLLM
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
    # Until ZetarisReader (agents) and Nightshift (models) land, agents read Postgres directly and any model
    # call fails loudly: the #7 path (structured questionnaire answers) makes none.
    app.state.ctx = Ctx(writer=writer, agent_reader=reader, ui_reader=reader, llm=FakeLLM(), wm=wm,
                        settings=settings, now=lambda: datetime.now(timezone.utc))
    try:
        yield
    finally:
        await pool.close()


app = FastAPI(title="TrialMatch", lifespan=lifespan)
app.include_router(router)
