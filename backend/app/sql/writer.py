"""app/sql/writer.py — the only path that writes Postgres."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Protocol, Sequence


class Tx(Protocol):
    async def execute(self, sql: str, params: Sequence[Any] = ()) -> None: ...
    async def fetch(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]: ...


class PgWriter:
    def __init__(self, pool) -> None: raise NotImplementedError

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[Tx]:
        raise NotImplementedError
        yield  # type: ignore[misc]
