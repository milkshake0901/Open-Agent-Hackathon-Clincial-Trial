"""app/sql/reader.py — the ADR 0001 read split as a protocol with two implementations.

Repo query functions are written ONCE against SqlReader. Table names pass through reader.table()
so Zetaris can qualify them (e.g. "trialmatch.fact"). Query text is ANSI SQL only; parameters are
positional and rendered by the reader (asyncpg $1 vs inlined literal for Zetaris, which takes a
single SQL string).
"""
from __future__ import annotations

from typing import Any, Protocol, Sequence

Row = dict[str, Any]


class SqlReader(Protocol):
    def table(self, name: str) -> str: ...
    async def fetch(self, sql: str, params: Sequence[Any] = ()) -> list[Row]: ...
    async def wait_visible(self, sql: str, params: Sequence[Any], *, expect_rows: int, timeout_s: float) -> list[Row]:
        """Read-after-write guard (ADR 0001 consequence). Pg returns immediately; Zetaris polls until the
        row count matches or the bound elapses, then raises NotYetVisible."""
        ...


class PgReader:
    def __init__(self, pool) -> None: raise NotImplementedError
    def table(self, name: str) -> str: raise NotImplementedError
    async def fetch(self, sql: str, params: Sequence[Any] = ()) -> list[Row]: raise NotImplementedError
    async def wait_visible(self, sql, params, *, expect_rows, timeout_s): raise NotImplementedError


class ZetarisReader:
    """POST {ZETARIS_REST_URL}/sql-editor/sqls/run with Authorization: Bearer, X-Org-ID: 1, fresh X-Request-ID
    per call; body {queryId, sql, source: "SqlEditor", limit}. One statement per request. Rows from response["data"].
    Logs every SQL for the sponsor-tech story."""
    def __init__(self, rest_url: str, api_key: str, datasource: str, http) -> None: raise NotImplementedError
    def table(self, name: str) -> str: raise NotImplementedError
    async def fetch(self, sql: str, params: Sequence[Any] = ()) -> list[Row]:
        """# TODO: render params as safe literals (dates, strings, int lists → IN (...)) because the REST API has no bind params."""
        raise NotImplementedError
    async def wait_visible(self, sql, params, *, expect_rows, timeout_s): raise NotImplementedError


class NotYetVisible(Exception): ...
