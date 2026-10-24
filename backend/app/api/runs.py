"""Runs and traces: how the system reasoned, and the patient's answer to a Conflict."""
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException

from app import trace
from app.api.deps import get_ctx
from app.ctx import Ctx
from app.trace.state import IngestRunState, reduce_ingest

router = APIRouter(tags=["runs"])


async def _read(ctx: Ctx, run_id: str, since: int = 0) -> trace.RunLog:
    try:
        return await trace.read(ctx.ui_reader, trace.RunId(run_id), since_seq=since)
    except trace.UnknownRun:
        raise HTTPException(404, f"run {run_id}")


def _events(log: trace.RunLog) -> list[dict]:
    return [{"seq": e.seq, "at": e.at, "kind": e.event.kind, "actor": e.actor, "causation_id": e.causation_id,
             "payload": e.event.model_dump(mode="json")} for e in log.events]


@router.get("/runs/{run_id}")
async def get_run(run_id: str, ctx: Ctx = Depends(get_ctx)):
    """{run_id, kind, head, state, events}. An ingest run's state.phase is started | drafting | awaiting_patient |
    committed | rejected; the upload page polls this until every run it started has ended."""
    log = await _read(ctx, run_id)
    state = None
    if log.kind == "ingest":
        folded = IngestRunState()
        for e in log.events:
            folded = reduce_ingest(folded, e.event)
        state = asdict(folded)
    return {"run_id": log.run_id, "kind": log.kind, "head": log.head, "state": state, "events": _events(log)}


@router.get("/runs/{run_id}/events")
async def run_events(run_id: str, since: int = 0, ctx: Ctx = Depends(get_ctx)):
    """Polled about once a second by the trace page while a run is live."""
    log = await _read(ctx, run_id, since)
    return {"head": log.head, "events": _events(log)}


@router.post("/runs/{run_id}/confirm", status_code=202)
async def confirm(run_id: str, body: dict):
    """Patient resolves Conflicts on a parked ingest run → record.confirm; 409 if not awaiting the patient."""
    raise NotImplementedError


@router.get("/traces/{correlation_id}")
async def trace_tree(correlation_id: str):
    """Causal tree across the ingest and its Re-scan, joined with llm_call (requested vs answered model)."""
    raise NotImplementedError
