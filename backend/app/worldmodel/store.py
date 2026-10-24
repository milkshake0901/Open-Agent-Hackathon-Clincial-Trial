"""app/worldmodel/store.py — where the engine's append-only event log lives.

InMemoryEventStore: tests and the conformance suite.
PgEventStore: the app. Appends the event, its audit entry AND the projection rows (projector.py)
in one Postgres transaction, so the log and the tables Zetaris reads can never disagree.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from app.sql.writer import PgWriter
    from app.worldmodel.engine import AuditEntry, WorldEvent


class EventStore(Protocol):
    async def append(self, event: "WorldEvent", audit: "AuditEntry") -> bool:
        """False if event.id already exists (duplicate after a crash); the engine treats that as a no-op."""
        ...

    async def load(self, namespace: str, *, since_seq: int = 0) -> list["WorldEvent"]: ...

    async def head(self, namespace: str) -> int: ...


class InMemoryEventStore:
    def __init__(self) -> None:
        self._events: dict[str, list["WorldEvent"]] = {}
        self._audit: dict[str, list["AuditEntry"]] = {}
        self._ids: set[tuple[str, str]] = set()

    async def append(self, event: "WorldEvent", audit: "AuditEntry") -> bool:
        key = (event.namespace, event.id)
        if key in self._ids:
            return False
        self._ids.add(key)
        self._events.setdefault(event.namespace, []).append(event)
        self._audit.setdefault(event.namespace, []).append(audit)
        return True

    async def load(self, namespace: str, *, since_seq: int = 0) -> list["WorldEvent"]:
        return [e for e in self._events.get(namespace, []) if e.seq > since_seq]

    async def head(self, namespace: str) -> int:
        events = self._events.get(namespace, [])
        return events[-1].seq if events else 0


class PgEventStore:
    """Tables wm_event and wm_audit (db/schema.sql). The only writer of them, and via projector.py
    the only writer of the domain tables fact, profile_version, trial, criterion, verdict, ..."""

    def __init__(self, writer: "PgWriter", namespace: str) -> None:
        self._writer = writer
        self.namespace = namespace

    async def append(self, event: "WorldEvent", audit: "AuditEntry") -> bool:
        from dataclasses import asdict

        from app.worldmodel import projector
        from app.worldmodel.stable_ids import canonical_json

        async with self._writer.transaction() as tx:
            inserted = await tx.fetch(
                "INSERT INTO wm_event (namespace, seq, id, kind, payload, at) VALUES ($1, $2, $3, $4, $5::jsonb, $6) "
                "ON CONFLICT (id) DO NOTHING RETURNING id",
                (event.namespace, event.seq, event.id, event.kind, canonical_json(asdict(event.payload)), event.at))
            if not inserted:
                return False
            await tx.execute(
                "INSERT INTO wm_audit (namespace, seq, at, kind, actor, summary, event_id, run_id) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
                (event.namespace, audit.seq, audit.at, audit.kind, audit.actor, audit.summary, audit.event_id,
                 audit.run_id))
            await projector.project(tx, event)
        return True

    async def load(self, namespace: str, *, since_seq: int = 0) -> list["WorldEvent"]:
        async with self._writer.transaction() as tx:
            rows = await tx.fetch("SELECT seq, id, kind, payload, at FROM wm_event WHERE namespace = $1 AND seq > $2 "
                                  "ORDER BY seq", (namespace, since_seq))
        return [_event_from_row(namespace, r) for r in rows]

    async def head(self, namespace: str) -> int:
        async with self._writer.transaction() as tx:
            rows = await tx.fetch("SELECT coalesce(max(seq), 0) AS head FROM wm_event WHERE namespace = $1",
                                  (namespace,))
        return int(rows[0]["head"])


def _event_from_row(namespace: str, row: dict) -> "WorldEvent":
    """Rebuild the dataclasses a WorldEvent payload was serialised from (asdict → JSON)."""
    import json

    from app.worldmodel.engine import Context, Entity, Fact, Provenance, Relationship, Snapshot, WorldEvent

    payload = json.loads(row["payload"]) if isinstance(row["payload"], str) else dict(row["payload"])
    payload["source"] = Provenance(**payload["source"])
    cls = {"upsertEntity": Entity, "upsertContext": Context, "relate": Relationship, "assertFact": Fact,
           "snapshot": Snapshot}[row["kind"]]
    for key in ("aliases", "entities"):
        if key in payload:
            payload[key] = tuple(payload[key])
    return WorldEvent(id=row["id"], seq=row["seq"], kind=row["kind"], payload=cls(**payload), at=row["at"],
                      namespace=namespace)
