"""app/worldmodel/engine.py — our Python implementation of the Meterless World Model engine.

Spec: Meterless/Meterless engines/world-model (AGENTS.md, reference/src/index.ts, conformance/runner.ts).
Scope: only what TrialMatch uses. The five write primitives (upsert_entity, upsert_context, relate,
assert_fact, snapshot), idempotent ingest, bitemporal reads, the audit log, stable ids and the
merge-band rule. Clustering, scoring and the operator control plane are out of scope.

Invariants (each one is a ported conformance check in tests/worldmodel/test_conformance.py):
  - No provenance, no write: every primitive raises MissingProvenance before touching state.
  - Record timestamps come from provenance.at (the observation time), never the wall clock.
  - Ingesting the same batch twice reports changed=False and leaves state_shape_canonical() unchanged.
  - A superseding relate() closes the old edge (sets valid_to) and opens a new one; nothing is deleted.
  - Every mutation appends one audit entry; audit seq is strictly increasing.

The engine is the ONLY writer of the domain tables it projects (see projector.py and ADR 0001).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Literal

from app.worldmodel.store import EventStore

ISODate = str
EventKind = Literal["upsertEntity", "upsertContext", "relate", "assertFact", "snapshot", "tombstone", "alias"]


class MissingProvenance(ValueError):
    """Raised at the boundary when a write has no provenance (conformance prov-001)."""


@dataclass(frozen=True)
class Provenance:
    """Who/what observed this, and when. `at` is the observation time and becomes the record time."""
    kind: str                      # "file" (a Document), "api" (ClinicalTrials.gov), "agent", "manual"
    at: ISODate
    by: str | None = None          # agent name or user id
    url: str | None = None         # for Documents: "doc:<hash>#page=<n>"
    checksum: str | None = None    # for Documents: the Document hash
    run_id: str | None = None      # joins the write to a trace run


@dataclass(frozen=True)
class Entity:
    type: str
    id: str
    attrs: dict[str, Any]
    source: Provenance
    created_at: ISODate
    updated_at: ISODate
    name: str | None = None
    aliases: tuple[str, ...] = ()
    state: Literal["emerging", "active", "archived"] = "active"


@dataclass(frozen=True)
class Context:
    type: str
    id: str
    attrs: dict[str, Any]
    source: Provenance
    parent: str | None = None


@dataclass(frozen=True)
class Relationship:
    """Bitemporal edge. valid_to None = open-ended. Superseded edges are closed, never deleted."""
    id: str
    from_id: str
    type: str
    to_id: str
    source: Provenance
    attrs: dict[str, Any] = field(default_factory=dict)
    context: str | None = None
    valid_from: ISODate | None = None
    valid_to: ISODate | None = None
    superseded_by: str | None = None


@dataclass(frozen=True)
class Fact:
    """An assertion about an entity. A later fact with the same (about, predicate) supersedes, never deletes."""
    id: str
    about: str
    predicate: str
    value: Any
    confidence: float
    source: Provenance
    asserted_at: ISODate
    context: str | None = None
    superseded_by: str | None = None


@dataclass(frozen=True)
class Snapshot:
    id: str
    at: ISODate
    entities: tuple[str, ...]
    source: Provenance
    attrs: dict[str, Any] = field(default_factory=dict)
    context: str | None = None


@dataclass(frozen=True)
class WorldEvent:
    id: str
    seq: int                       # monotonic within the namespace, by append order
    kind: EventKind
    payload: Entity | Context | Relationship | Fact | Snapshot
    at: ISODate


@dataclass(frozen=True)
class AuditEntry:
    seq: int
    at: ISODate
    kind: str
    actor: str
    summary: str
    event_id: str | None = None
    run_id: str | None = None


@dataclass(frozen=True)
class IngestObservation:
    external_id: str               # dedupe key derives from it (e.g. the NCT ID)
    title: str
    at: ISODate
    source: Provenance
    type: str = "item"
    text: str | None = None
    attrs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class IngestReport:
    run_id: str
    processed: int
    skipped_unchanged: int
    events_appended: int
    changed: bool
    changed_ids: tuple[str, ...]   # entity ids whose content changed; drives a narrowed Re-scan


class WorldModel:
    def __init__(self, *, namespace: str, store: EventStore,
                 clock: Callable[[], datetime] | None = None) -> None:
        """`store` holds the append-only event log (InMemoryEventStore in tests, PgEventStore in the app).
        `clock` is used only for genuinely-now operator actions, never for record timestamps."""
        raise NotImplementedError

    # ---- write primitives (all async: the Postgres store appends in a transaction) ----

    async def upsert_entity(self, *, type: str, source: Provenance | None, name: str | None = None,
                            external_key: tuple[str, str] | None = None, attrs: dict[str, Any] | None = None) -> Entity:
        """Id = external key ("type:system:id") when given, else entity_id_from_name(type, name).
        # TODO: reject missing provenance; merge attrs; keep aliases; no-op (no event) if unchanged."""
        raise NotImplementedError

    async def upsert_context(self, *, type: str, id: str, source: Provenance | None,
                             attrs: dict[str, Any] | None = None, parent: str | None = None) -> Context:
        raise NotImplementedError

    async def relate(self, *, from_id: str, type: str, to_id: str, source: Provenance | None,
                     valid_from: ISODate | None = None, attrs: dict[str, Any] | None = None,
                     context: str | None = None) -> Relationship:
        """# TODO: if an open edge (from_id, type) exists to a different to_id or with different attrs,
        close it (valid_to = valid_from of the new edge, superseded_by = new id) and open the new one."""
        raise NotImplementedError

    async def assert_fact(self, *, about: str, predicate: str, value: Any, source: Provenance | None,
                          confidence: float = 1.0, context: str | None = None) -> Fact:
        """# TODO: fact id is content-derived (stable_ids.fact_id) so re-asserting the same fact is a no-op.
        Supersession by observation time: the fact with the latest source.at is current; an older
        observation arriving late is stored but marked superseded (ADR 0002)."""
        raise NotImplementedError

    async def snapshot(self, *, entities: list[str], source: Provenance | None,
                       attrs: dict[str, Any] | None = None, context: str | None = None) -> Snapshot:
        raise NotImplementedError

    async def ingest(self, observations: list[IngestObservation], *, run_id: str | None = None) -> IngestReport:
        """Idempotent batch upsert keyed by external_id + content checksum (conformance idem-001/002)."""
        raise NotImplementedError

    # ---- reads ----

    def entity(self, id: str) -> Entity | None: raise NotImplementedError
    def entity_at(self, id: str, at: ISODate) -> Entity | None: raise NotImplementedError
    def about(self, id: str, *, include_superseded: bool = False) -> list[Fact]: raise NotImplementedError

    def neighbors_of(self, id: str, *, via: str | None = None, at: ISODate | None = None) -> list[Entity]:
        """Open edges by default; `at` returns edges valid at that instant (conformance bitemp-001)."""
        raise NotImplementedError

    def edges_from(self, id: str, *, via: str | None = None, at: ISODate | None = None) -> list[Relationship]:
        raise NotImplementedError

    def events(self, *, since_seq: int = 0) -> list[WorldEvent]: raise NotImplementedError
    def audit(self) -> list[AuditEntry]: raise NotImplementedError
    def state_shape_canonical(self) -> str:
        """Canonical JSON of the folded state; equal strings mean equal worlds (idempotency check)."""
        raise NotImplementedError
