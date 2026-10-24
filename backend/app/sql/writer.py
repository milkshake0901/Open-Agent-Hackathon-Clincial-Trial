"""app/sql/writer.py — the only path that writes Postgres."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Protocol, Sequence


class Tx(Protocol):
    async def execute(self, sql: str, params: Sequence[Any] = ()) -> None: ...
    async def fetch(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]: ...


class _PgTx:
    def __init__(self, conn) -> None:
        self._conn = conn

    async def execute(self, sql: str, params: Sequence[Any] = ()) -> None:
        await self._conn.execute(sql, *params)

    async def fetch(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        return [dict(r) for r in await self._conn.fetch(sql, *params)]


class PgWriter:
    def __init__(self, pool) -> None:
        self._pool = pool

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[Tx]:
        async with self._pool.acquire() as conn, conn.transaction():
            yield _PgTx(conn)
