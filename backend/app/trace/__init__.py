"""app/trace — how the system reasoned. Owns the trace_event and llm_call tables (sole writer).

A run is one unit of work the user started (an ingest of one Document, or a Re-scan). Every
loop step, retry, rejection and model call inside it is appended here, so the trace page
shows the reasoning without any separate logging code that could drift from what happened.

Envelope on every event:
  event_id        stable_ids.event_id(actor, cause, index) → a duplicate append after a crash is ignored
  actor           which agent or rule produced it ("intake", "critic", "matcher", "evaluator", "rescan")
  causation_id    the event this one reacts to → the UI draws a causal tree, not a flat list
  correlation_id  the run id the user started; one upload threads through ingest AND its Re-scan
  llm_call_ids    joins to llm_call (requested vs answered model, latency, tokens)

World Model writes carry the run id in their provenance, so a trace links to the world changes it caused.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, NewType

if TYPE_CHECKING:
    from app.sql.reader import SqlReader
    from app.sql.writer import PgWriter
    from app.trace.events import RunEvent
    from app.trace.state import IngestRunState, RescanRunState

RunId = NewType("RunId", str)
EventId = NewType("EventId", str)
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


def new_id() -> RunId: raise NotImplementedError


async def open(writer: "PgWriter", run_id: RunId, kind: RunKind, *, patient_id: str | None,
               document_hash: str | None = None, correlation_id: RunId | None = None) -> None:
    """Idempotent create. A Re-scan started by an ingest shares the ingest's correlation id."""
    raise NotImplementedError


async def append(writer: "PgWriter", run_id: RunId, event: "RunEvent", *,
                 caused_by: EventId | None = None, llm_call_ids: tuple[str, ...] = ()) -> EventId:
    """Concurrent appends from parallel Matcher tasks are fine: seq is allocated by the database."""
    raise NotImplementedError


async def record_llm_call(writer: "PgWriter", run_id: RunId | None, call: LlmCall) -> str:
    raise NotImplementedError


async def read(reader: "SqlReader", run_id: RunId, *, since_seq: int = 0) -> RunLog:
    raise NotImplementedError


async def causal_tree(reader: "SqlReader", correlation_id: RunId) -> list[TracedEvent]:
    """Every event across all runs sharing this correlation id, ordered for tree rendering."""
    raise NotImplementedError


async def project_ingest(reader: "SqlReader", run_id: RunId) -> "IngestRunState": raise NotImplementedError
async def project_rescan(reader: "SqlReader", run_id: RunId) -> "RescanRunState": raise NotImplementedError


async def latest_for_document(reader: "SqlReader", document_hash: str) -> RunId | None:
    """For ingest() idempotency when a run for this Document is parked awaiting the patient."""
    raise NotImplementedError
