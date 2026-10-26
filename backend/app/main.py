"""app/main.py — FastAPI app. The lifespan builds one Ctx: Postgres pool and writer, PgReader (UI),
ZetarisReader (agents), the Nightshift client, Nemotron Parse, and the World Model with PgEventStore (replayed from
wm_event)."""
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import asyncpg
import httpx
from fastapi import FastAPI

from app import logfile, trials
from app.api import EXCEPTION_HANDLERS, router
from app.config import Settings
from app.ctx import Ctx
from app.extraction import NemotronParse
from app.llm.direct import connect
from app.sql.reader import PgReader, ZetarisReader, pg_column_types
from app.sql.writer import PgWriter
from app.worldmodel import PgEventStore, WorldModel

WORLD_MODEL_NAMESPACE = "trialmatch"
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if getattr(app.state, "ctx", None) is not None:   # tests install their own Ctx
        yield
        return
    settings = Settings()
    logfile.configure(settings.log_file, max_bytes=settings.log_max_bytes, backups=settings.log_backups)
    pool = await asyncpg.create_pool(settings.pg_dsn, min_size=1, max_size=8)
    writer = PgWriter(pool)
    reader = PgReader(pool)
    wm = WorldModel(namespace=WORLD_MODEL_NAMESPACE, store=PgEventStore(writer, WORLD_MODEL_NAMESPACE))
    await wm.replay()
    llm = connect(settings)   # Nightshift, with DIRECT_LANES on NVIDIA's API when NVIDIA_API_KEY is set
    await llm.models()   # warns, never fails: a missing runtime turns model calls into LlmUnavailable
    zetaris_http = httpx.AsyncClient()
    if settings.zetaris_api_key:
        agent_reader = ZetarisReader(settings.zetaris_rest_url, settings.zetaris_api_key, settings.zetaris_org_id,
                                     settings.zetaris_datasource, zetaris_http, await pg_column_types(pool))
    else:
        log.warning("ZETARIS_API_KEY is not set: agents read Postgres directly, not through Zetaris (ADR 0001)")
        agent_reader = reader
    app.state.ctx = Ctx(writer=writer, agent_reader=agent_reader, ui_reader=reader, llm=llm,
                        parser=NemotronParse(settings),   # its client is built on the first read: no key, no crash
                        wm=wm, settings=settings, now=lambda: datetime.now(timezone.utc))
    # Trials come from the saved snapshot until the Australia-wide ingest (backend/scripts/ingest_trials.py) has
    # run; idempotent across restarts.
    await trials.load_snapshot(app.state.ctx, settings.trials_snapshot_dir)
    try:
        yield
    finally:
        await llm.aclose()
        await zetaris_http.aclose()
        await pool.close()


app = FastAPI(title="TrialMatch", lifespan=lifespan, exception_handlers=EXCEPTION_HANDLERS)
app.include_router(router)
