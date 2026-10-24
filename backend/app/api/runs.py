"""Runs and traces: how the system reasoned, and the patient's answer to a Conflict."""
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException

from app import matching, record, trace
from app.api.deps import get_ctx
from app.api.schemas import ConfirmIn, ConflictOut, ConflictSideOut, ConflictsOut, RescanSummary, IngestOutcomeOut
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


async def _side(ctx: Ctx, h: str, page: int, quote: str, value: str, unit: str | None, observed_on,
                question: str | None) -> ConflictSideOut:
    doc = await record.document(ctx, record.DocumentHash(h))
    text = next((p.text for p in doc.pages if p.number == page), "")
    label = f"Patient-reported, intake questionnaire, {question}" if question else f"{doc.filename}, page {page}"
    return ConflictSideOut(document_hash=h, filename=doc.filename, page=page, page_text=text, quote=quote, value=value,
                           unit=unit, observed_on=observed_on, label=label)


async def _conflict_out(ctx: Ctx, c: record.Conflict) -> ConflictOut:
    d, a = c.draft, c.accepted
    return ConflictOut(
        id=c.id, message=c.message,
        draft=await _side(ctx, c.document_hash, d.page, d.quote, d.value, d.unit, d.observed_on, d.question),
        accepted=a and await _side(ctx, a.document_hash, a.page, a.quote, a.value, a.unit, a.observed_on, a.question))


@router.get("/runs/{run_id}/conflicts", response_model=ConflictsOut)
async def conflicts(run_id: str, ctx: Ctx = Depends(get_ctx)):
    """The Conflicts a parked ingest run waits on, each side with its Document, page and quote (the Conflict dialog)."""
    try:
        found = await record.conflicts(ctx, trace.RunId(run_id))
    except record.NotFound as e:
        raise HTTPException(404, str(e))
    return ConflictsOut(run_id=run_id, conflicts=[await _conflict_out(ctx, c) for c in found])


def submission_accepted(outcome: record.IngestOutcome) -> IngestOutcomeOut:
    match outcome:
        case record.Committed(run_id=run_id, version=v):
            return IngestOutcomeOut(run_id=run_id, outcome="committed", document_hash=v.document_hash,
                                      profile_version_id=v.id, version_number=v.number)
        case record.AwaitingPatient(run_id=run_id):
            return IngestOutcomeOut(run_id=run_id, outcome="awaiting_patient")
        case record.Rejected(run_id=run_id, reason=reason):
            return IngestOutcomeOut(run_id=run_id, outcome="rejected", reason=reason)


@router.post("/runs/{run_id}/confirm", status_code=202, response_model=IngestOutcomeOut)
async def confirm(run_id: str, body: ConfirmIn, ctx: Ctx = Depends(get_ctx)):
    """Patient resolves Conflicts on a parked ingest run → record.confirm. Committed re-scans the new version under
    the run's correlation id, as an upload does. 404 unknown run, 409 not awaiting the patient, 422 unknown Conflict."""
    try:
        outcome = await record.confirm(ctx, trace.RunId(run_id), [
            record.Resolution(record.ConflictId(r.conflict_id), r.choice) for r in body.resolutions])
    except record.NotFound as e:
        raise HTTPException(404, str(e))
    except record.NotAwaitingPatient as e:
        raise HTTPException(409, str(e))
    except record.InvalidResolution as e:
        raise HTTPException(422, str(e))
    accepted = submission_accepted(outcome)
    if isinstance(outcome, record.Committed):
        report = await matching.rescan(ctx, outcome.version.id, correlation_id=outcome.run_id)
        accepted.rescan = RescanSummary(judged=len(report.judged), failed=len(report.failed))
    return accepted


@router.get("/traces/{correlation_id}")
async def trace_tree(correlation_id: str):
    """Causal tree across the ingest and its Re-scan, joined with llm_call (requested vs answered model)."""
    raise NotImplementedError
