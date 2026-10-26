"""app/trace — how the system reasoned. Owns the trace_event and llm_call tables (sole writer).

A run is one unit of work the user started (an ingest of one Document, or a Re-scan). Every
loop step, retry, rejection and model call inside it is appended here, so the trace page
shows the reasoning without any separate logging code that could drift from what happened.

Envelope on every event:
  event_id        stable_ids.event_id(actor, cause, index) → a duplicate append after a crash is ignored
  actor           which agent or rule produced it ("intake", "critic", "matcher", "evaluator", "rescan")
  causation_id    the event this one reacts to → the UI draws a causal tree, not a flat list
  correlation_id  the run id the user started; one added Document threads through ingest AND its Re-scan
  llm_call_ids    joins to llm_call (requested vs answered model, latency, tokens)

World Model writes carry the run id in their provenance, so a trace links to the world changes it caused.
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, NewType

from app import logfile

if TYPE_CHECKING:
    from app.sql.reader import SqlReader
    from app.sql.writer import PgWriter
    from app.trace.events import RunEvent
    from app.trace.state import IngestRunState, RescanRunState

RunId = NewType("RunId", str)
EventId = NewType("EventId", str)
log = logging.getLogger(__name__)
RunKind = Literal["ingest", "rescan"]


@dataclass(frozen=True)
class TracedEvent:
    event_id: EventId
    seq: int
    at: str
    actor: str
    causation_id: EventId | None
    event: "RunEvent"


@dataclass(frozen=True)
class LlmCall:
    id: str
    lane: str
    model_requested: str
    model_answered: str
    latency_ms: int
    prompt_tokens: int
    completion_tokens: int
    ok: bool


@dataclass(frozen=True)
class RunLog:
    run_id: RunId
    kind: RunKind
    head: int
    events: tuple[TracedEvent, ...]
    llm_calls: tuple[LlmCall, ...]


_EVENT_NS = uuid.UUID("0b5f8f8e-4d0e-4a53-9c3f-6a2a3f1d7c10")


def new_id() -> RunId:
    return RunId(f"run_{uuid.uuid4().hex}")


async def open(writer: "PgWriter", run_id: RunId, kind: RunKind, *, patient_id: str | None,
               document_hash: str | None = None, correlation_id: RunId | None = None) -> None:
    """Idempotent create. A Re-scan started by an ingest shares the ingest's correlation id."""
    async with writer.transaction() as tx:
        await tx.execute(
            "INSERT INTO trace_run (id, kind, correlation_id, patient_id, document_hash) VALUES ($1, $2, $3, $4, $5) "
            "ON CONFLICT (id) DO NOTHING",
            (run_id, kind, correlation_id or run_id, patient_id, document_hash))


async def append(writer: "PgWriter", run_id: RunId, event: "RunEvent", *,
                 caused_by: EventId | None = None, llm_call_ids: tuple[str, ...] = ()) -> EventId:
    """Concurrent appends from parallel Matcher tasks are fine: seq is allocated by the database.
    The event id is derived from (run, actor, payload, cause), so appending the same event twice is a no-op.
    An event with a `log_step` also writes one line to the log file: the run id and the payload's fields."""
    payload = event.model_dump(mode="json")
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    event_id = EventId(str(uuid.uuid5(_EVENT_NS, f"{run_id}|{event.actor}|{body}|{caused_by or ''}")))
    async with writer.transaction() as tx:
        await tx.execute(
            "INSERT INTO trace_event (event_id, run_id, kind, actor, causation_id, llm_call_ids, payload) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb) ON CONFLICT (event_id) DO NOTHING",
            (event_id, run_id, payload["kind"], event.actor, caused_by, list(llm_call_ids), body))
    if event.log_step:
        logfile.step(log, event.log_step, run_id=run_id,
                     **{k: v for k, v in payload.items() if k not in ("kind", "actor")})
    return event_id


async def record_llm_call(writer: "PgWriter", run_id: RunId | None, call: LlmCall) -> str:
    """One row per model call, failed ones included (ok=False), so the trace shows which model answered."""
    async with writer.transaction() as tx:
        await tx.execute(
            "INSERT INTO llm_call (id, run_id, lane, model_requested, model_answered, prompt_tokens, "
            "completion_tokens, latency_ms, ok) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9) ON CONFLICT (id) DO NOTHING",
            (call.id, run_id, str(call.lane), call.model_requested, call.model_answered, call.prompt_tokens,
             call.completion_tokens, call.latency_ms, call.ok))
    return call.id


class UnknownRun(LookupError):
    """No run with this id."""


async def read(reader: "SqlReader", run_id: RunId, *, since_seq: int = 0) -> RunLog:
    """The run's events after `since_seq` (in append order) and its model calls. `head` is the run's last seq, so a
    poller passes it back as `since_seq`. Raises UnknownRun."""
    from pydantic import TypeAdapter

    from app.trace.events import RunEvent

    runs = await reader.fetch(f"SELECT kind FROM {reader.table('trace_run')} WHERE id = $1", (run_id,))
    if not runs:
        raise UnknownRun(run_id)
    rows = await reader.fetch(
        f"SELECT event_id, seq, at, actor, causation_id, payload FROM {reader.table('trace_event')} "
        "WHERE run_id = $1 AND seq > $2 ORDER BY seq", (run_id, since_seq))
    head = await reader.fetch(f"SELECT coalesce(max(seq), 0) AS head FROM {reader.table('trace_event')} "
                              "WHERE run_id = $1", (run_id,))
    calls = await reader.fetch(
        f"SELECT id, lane, model_requested, model_answered, latency_ms, prompt_tokens, completion_tokens, ok "
        f"FROM {reader.table('llm_call')} WHERE run_id = $1 ORDER BY at, id", (run_id,))
    adapter = TypeAdapter(RunEvent)
    events = tuple(TracedEvent(
        event_id=EventId(r["event_id"]), seq=r["seq"], at=r["at"].isoformat(), actor=r["actor"],
        causation_id=r["causation_id"],
        event=adapter.validate_python(json.loads(r["payload"]) if isinstance(r["payload"], str) else r["payload"]))
        for r in rows)
    return RunLog(run_id=run_id, kind=runs[0]["kind"], head=head[0]["head"], events=events,
                  llm_calls=tuple(LlmCall(**c) for c in calls))


async def causal_tree(reader: "SqlReader", correlation_id: RunId) -> list[TracedEvent]:
    """Every event across all runs sharing this correlation id, ordered for tree rendering."""
    raise NotImplementedError


async def project_ingest(reader: "SqlReader", run_id: RunId) -> "IngestRunState":
    """The ingest run's state, folded from its whole log. Raises UnknownRun."""
    from app.trace.state import IngestRunState, reduce_ingest

    state = IngestRunState()
    for traced in (await read(reader, run_id)).events:
        state = reduce_ingest(state, traced.event)
    return state


async def project_rescan(reader: "SqlReader", run_id: RunId) -> "RescanRunState": raise NotImplementedError


async def latest_for_document(reader: "SqlReader", document_hash: str) -> RunId | None:
    """For ingest() idempotency when a run for this Document is parked awaiting the patient."""
    rows = await reader.fetch(f"SELECT id FROM {reader.table('trace_run')} WHERE document_hash = $1 "
                              "ORDER BY created_at DESC, id DESC LIMIT 1", (document_hash,))
    return RunId(rows[0]["id"]) if rows else None
