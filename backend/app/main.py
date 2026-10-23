"""app/main.py — FastAPI app. The lifespan builds one Ctx: Postgres pool and writer, PgReader (UI),
ZetarisReader (agents), the Nightshift client, and the World Model with PgEventStore."""
from fastapi import FastAPI

from app.api import router

app = FastAPI(title="TrialMatch")
app.include_router(router)

# TODO: lifespan → Settings() → Ctx(...); stash on app.state; close pools on shutdown.
