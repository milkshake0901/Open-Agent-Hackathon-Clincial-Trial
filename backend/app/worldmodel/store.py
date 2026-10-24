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
        raise NotImplementedError
