"""Runs and traces: how the system reasoned, and the patient's answer to a Conflict."""
from fastapi import APIRouter

router = APIRouter(tags=["runs"])


@router.get("/runs/{run_id}")
async def get_run(run_id: str): raise NotImplementedError


@router.get("/runs/{run_id}/events")
async def run_events(run_id: str, since: int = 0):
    """Polled about once a second by the trace page while a run is live."""
    raise NotImplementedError


@router.post("/runs/{run_id}/confirm", status_code=202)
async def confirm(run_id: str, body: dict):
    """Patient resolves Conflicts on a parked ingest run → record.confirm; 409 if not awaiting the patient."""
    raise NotImplementedError


@router.get("/traces/{correlation_id}")
async def trace_tree(correlation_id: str):
    """Causal tree across the ingest and its Re-scan, joined with llm_call (requested vs answered model)."""
    raise NotImplementedError
