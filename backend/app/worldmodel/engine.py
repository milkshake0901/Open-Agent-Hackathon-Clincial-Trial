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

import asyncio
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Callable, Literal

from app.worldmodel.stable_ids import canonical_json, entity_id_from_name, event_id, fact_id, sha256_hex
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
    namespace: str = ""


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


def _require(source: Provenance | None, op: str) -> Provenance:
    if source is None:
        raise MissingProvenance(f"{op} requires provenance")
    return source


def _actor(source: Provenance) -> str:
    return source.by or source.kind


def _content_hash(value: Any) -> str:
    return sha256_hex(canonical_json(value))


class WorldModel:
    def __init__(self, *, namespace: str, store: EventStore,
                 clock: Callable[[], datetime] | None = None) -> None:
        """`store` holds the append-only event log (InMemoryEventStore in tests, PgEventStore in the app).
        `clock` is used only for genuinely-now operator actions, never for record timestamps."""
        self.namespace = namespace
        self._store = store
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._seq = 0
        self._append_lock = asyncio.Lock()
        self._events: list[WorldEvent] = []
        self._audit: list[AuditEntry] = []
        self._entities: dict[str, Entity] = {}
        self._contexts: dict[str, Context] = {}
        self._edges: dict[str, Relationship] = {}
        self._facts: dict[str, Fact] = {}
        self._snapshots: dict[str, Snapshot] = {}

    async def replay(self) -> int:
        """Fold the store's existing log into memory (app start-up over PgEventStore). Returns the head seq.
        Appends nothing, so it is safe to call on an empty store."""
        for event in await self._store.load(self.namespace, since_seq=self._seq):
            self._events.append(event)
            self._fold(event)
            self._seq = event.seq
        return self._seq

    # ---- the single append path: store first, then fold ----

    async def _append(self, kind: EventKind, payload: Any, source: Provenance, summary: str) -> bool:
        # One append at a time: seq is taken from memory, so concurrent writers (two uploads ingesting at once)
        # would otherwise both claim the same seq.
        async with self._append_lock:
            return await self._append_one(kind, payload, source, summary)

    async def _append_one(self, kind: EventKind, payload: Any, source: Provenance, summary: str) -> bool:
        seq = self._seq + 1
        cause = f"{kind}:{payload.id}:{_content_hash(asdict(payload))}"
        event = WorldEvent(id=event_id(f"{self.namespace}/{_actor(source)}", cause, seq), seq=seq,
                           kind=kind, payload=payload, at=source.at, namespace=self.namespace)
        audit = AuditEntry(seq=seq, at=source.at, kind=kind, actor=_actor(source), summary=summary,
                           event_id=event.id, run_id=source.run_id)
        if not await self._store.append(event, audit):
            return False
        self._seq = seq
        self._events.append(event)
        self._audit.append(audit)
        self._fold(event)
        return True

    def _fold(self, event: WorldEvent) -> None:
        p = event.payload
        if isinstance(p, Entity):
            self._entities[p.id] = p
        elif isinstance(p, Context):
            self._contexts[p.id] = p
        elif isinstance(p, Relationship):
            self._edges[p.id] = p
        elif isinstance(p, Fact):
            self._facts[p.id] = p
        elif isinstance(p, Snapshot):
            self._snapshots[p.id] = p

    # ---- write primitives (all async: the Postgres store appends in a transaction) ----

    async def upsert_entity(self, *, type: str, source: Provenance | None, name: str | None = None,
                            external_key: tuple[str, str] | None = None, attrs: dict[str, Any] | None = None) -> Entity:
        """Id = external key ("type:system:id") when given, else entity_id_from_name(type, name).
        Attrs merge over the existing ones; a new name is kept as an alias; unchanged = no event."""
        source = _require(source, "upsert_entity")
        if external_key is not None:
            id = f"{type}:{external_key[0]}:{external_key[1]}"
        elif name is not None:
            id = entity_id_from_name(type, name)
        else:
            raise ValueError("upsert_entity needs a name or an external_key")
        old = self._entities.get(id)
        if old is None:
            new = Entity(type=type, id=id, attrs=dict(attrs or {}), source=source,
                         created_at=source.at, updated_at=source.at, name=name)
        else:
            merged = {**old.attrs, **(attrs or {})}
            aliases = old.aliases
            if name is not None and old.name is not None and name != old.name and name not in aliases:
                aliases = aliases + (name,)
            if merged == old.attrs and aliases == old.aliases and (name is None or old.name is not None):
                return old
            new = replace(old, attrs=merged, aliases=aliases, name=old.name or name,
                          source=source, updated_at=source.at)
        await self._append("upsertEntity", new, source, f"upsert {id}")
        return self._entities.get(id, new)

    async def upsert_context(self, *, type: str, id: str, source: Provenance | None,
                             attrs: dict[str, Any] | None = None, parent: str | None = None) -> Context:
        source = _require(source, "upsert_context")
        old = self._contexts.get(id)
        merged = {**(old.attrs if old else {}), **(attrs or {})}
        if old is not None and old.attrs == merged and old.parent == (parent or old.parent):
            return old
        new = Context(type=type, id=id, attrs=merged, source=source,
                      parent=parent if parent is not None else (old.parent if old else None))
        await self._append("upsertContext", new, source, f"context {id}")
        return new

    async def relate(self, *, from_id: str, type: str, to_id: str, source: Provenance | None,
                     valid_from: ISODate | None = None, attrs: dict[str, Any] | None = None,
                     context: str | None = None) -> Relationship:
        """If an open edge (from_id, type, context) exists to a different to_id or with different attrs,
        close it (valid_to = valid_from of the new edge, superseded_by = new id) and open the new one."""
        source = _require(source, "relate")
        valid_from = valid_from or source.at
        attrs = dict(attrs or {})
        open_edges = [e for e in self._edges.values()
                      if e.from_id == from_id and e.type == type and e.context == context and e.valid_to is None]
        for e in open_edges:
            if e.to_id == to_id and e.attrs == attrs:
                return e
        new_id = "rel:" + _content_hash([from_id, type, to_id, valid_from, attrs, context])[:32]
        for e in open_edges:
            closed = replace(e, valid_to=valid_from, superseded_by=new_id)
            await self._append("relate", closed, source, f"close {e.id}")
        new = Relationship(id=new_id, from_id=from_id, type=type, to_id=to_id, source=source,
                           attrs=attrs, context=context, valid_from=valid_from)
        await self._append("relate", new, source, f"relate {from_id} -{type}-> {to_id}")
        return new

    async def assert_fact(self, *, about: str, predicate: str, value: Any, source: Provenance | None,
                          confidence: float = 1.0, context: str | None = None) -> Fact:
        """Fact id is content-derived (stable_ids.fact_id) so re-asserting the same fact is a no-op.
        Supersession by observation time: the fact with the latest source.at is current; an older
        observation arriving late is stored but marked superseded (ADR 0002)."""
        source = _require(source, "assert_fact")
        id = fact_id(about, predicate, value, source.at, source.checksum)
        if id in self._facts:
            return self._facts[id]
        current = next((f for f in self._facts.values()
                        if f.about == about and f.predicate == predicate and f.superseded_by is None), None)
        new = Fact(id=id, about=about, predicate=predicate, value=value, confidence=confidence,
                   source=source, asserted_at=source.at, context=context)
        if current is not None and source.at < current.source.at:
            new = replace(new, superseded_by=current.id)
        elif current is not None:
            await self._append("assertFact", replace(current, superseded_by=id), source, f"supersede {current.id}")
        await self._append("assertFact", new, source, f"fact {about} {predicate}")
        return new

    async def snapshot(self, *, entities: list[str], source: Provenance | None,
                       attrs: dict[str, Any] | None = None, context: str | None = None) -> Snapshot:
        source = _require(source, "snapshot")
        attrs = dict(attrs or {})
        id = "snap:" + _content_hash([sorted(entities), source.at, attrs, context])[:32]
        if id in self._snapshots:
            return self._snapshots[id]
        new = Snapshot(id=id, at=source.at, entities=tuple(entities), source=source, attrs=attrs, context=context)
        await self._append("snapshot", new, source, f"snapshot {', '.join(entities)}")
        return new

    async def ingest(self, observations: list[IngestObservation], *, run_id: str | None = None) -> IngestReport:
        """Idempotent batch upsert keyed by external_id + content checksum (conformance idem-001/002)."""
        checksums = [_content_hash([o.type, o.external_id, o.title, o.text, o.attrs]) for o in observations]
        run_id = run_id or "ingest:" + _content_hash(checksums)[:16]
        before = self._seq
        skipped = 0
        changed: list[str] = []
        for obs, checksum in zip(observations, checksums):
            id = f"{obs.type}:{obs.external_id}"
            old = self._entities.get(id)
            if old is not None and old.attrs.get("checksum") == checksum:
                skipped += 1
                continue
            source = replace(_require(obs.source, "ingest"), run_id=obs.source.run_id or run_id)
            attrs = {**obs.attrs, "external_id": obs.external_id, "title": obs.title, "text": obs.text,
                     "observed_at": obs.at, "checksum": checksum}
            # Full replacement, not a merge: the observation is the whole current content.
            new = Entity(type=obs.type, id=id, attrs=attrs, source=source, name=obs.title,
                         created_at=old.created_at if old else source.at, updated_at=source.at,
                         aliases=old.aliases if old else ())
            if await self._append("upsertEntity", new, source, f"ingest {id}"):
                changed.append(id)
        appended = self._seq - before
        return IngestReport(run_id=run_id, processed=len(observations), skipped_unchanged=skipped,
                            events_appended=appended, changed=appended > 0, changed_ids=tuple(changed))

    # ---- reads ----

    def entity(self, id: str) -> Entity | None:
        return self._entities.get(id)

    def entity_at(self, id: str, at: ISODate) -> Entity | None:
        found = None
        for e in self._events:
            if isinstance(e.payload, Entity) and e.payload.id == id and e.payload.updated_at <= at:
                found = e.payload
        return found

    def about(self, id: str, *, include_superseded: bool = False) -> list[Fact]:
        facts = [f for f in self._facts.values() if f.about == id and (include_superseded or f.superseded_by is None)]
        return sorted(facts, key=lambda f: (f.asserted_at, f.id))

    def neighbors_of(self, id: str, *, via: str | None = None, at: ISODate | None = None) -> list[Entity]:
        """Open edges by default; `at` returns edges valid at that instant (conformance bitemp-001)."""
        return [self._entities[e.to_id] for e in self.edges_from(id, via=via, at=at) if e.to_id in self._entities]

    def edges_from(self, id: str, *, via: str | None = None, at: ISODate | None = None) -> list[Relationship]:
        def valid(e: Relationship) -> bool:
            if at is None:
                return e.valid_to is None
            return (e.valid_from is None or e.valid_from <= at) and (e.valid_to is None or at < e.valid_to)
        return [e for e in self._edges.values() if e.from_id == id and (via is None or e.type == via) and valid(e)]

    def snapshots(self) -> list[Snapshot]:
        """In append order."""
        return [e.payload for e in self._events if isinstance(e.payload, Snapshot)]

    def events(self, *, since_seq: int = 0) -> list[WorldEvent]:
        return [e for e in self._events if e.seq > since_seq]

    def audit(self) -> list[AuditEntry]:
        return list(self._audit)

    def state_shape_canonical(self) -> str:
        """Canonical JSON of the folded state; equal strings mean equal worlds (idempotency check).
        Provenance run ids are excluded: re-running the same batch under a new run is the same world."""
        def strip(x: Any) -> Any:
            d = asdict(x)
            d.get("source", {}).pop("run_id", None)
            return d
        return canonical_json({
            "entities": {k: strip(v) for k, v in self._entities.items()},
            "contexts": {k: strip(v) for k, v in self._contexts.items()},
            "relationships": {k: strip(v) for k, v in self._edges.items()},
            "facts": {k: strip(v) for k, v in self._facts.items()},
            "snapshots": {k: strip(v) for k, v in self._snapshots.items()},
        })
