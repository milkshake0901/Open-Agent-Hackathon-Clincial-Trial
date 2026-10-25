"""app/sql/reader.py — the ADR 0001 read split as a protocol with two implementations.

Repo query functions are written ONCE against SqlReader. Table names pass through reader.table()
so Zetaris can qualify them (e.g. "trialmatch.fact"). Query text is ANSI SQL only; parameters are
positional and rendered by the reader (asyncpg $1 vs inlined literal for Zetaris, which takes a
single SQL string).
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from datetime import date, datetime, timezone
from typing import Any, Mapping, Protocol, Sequence

import httpx

Row = dict[str, Any]


class SqlReader(Protocol):
    def table(self, name: str) -> str: ...
    async def fetch(self, sql: str, params: Sequence[Any] = ()) -> list[Row]: ...
    async def wait_visible(self, sql: str, params: Sequence[Any], *, expect_rows: int, timeout_s: float) -> list[Row]:
        """Read-after-write guard (ADR 0001 consequence). Pg returns immediately; Zetaris polls until the
        row count matches or the bound elapses, then raises NotYetVisible."""
        ...


class PgReader:
    """Reads our Postgres directly (the HTTP shell, and agents in tests). Writes are visible at once."""
    def __init__(self, pool) -> None:
        self._pool = pool

    def table(self, name: str) -> str:
        return name

    async def fetch(self, sql: str, params: Sequence[Any] = ()) -> list[Row]:
        return [dict(r) for r in await self._pool.fetch(sql, *params)]

    async def wait_visible(self, sql, params, *, expect_rows, timeout_s):
        return await self.fetch(sql, params)


class ZetarisReader:
    """POST {ZETARIS_REST_URL}/sql-editor/sqls/run with Authorization: Bearer, X-Org-ID, fresh X-Request-ID
    per call; body {queryId, sql, source: "SqlEditor", limit}. One statement per request. Logs every SQL for the
    sponsor-tech story.

    Zetaris answers {headers, data, total, timeUsed} with every non-null value as a string, so `column_types`
    (pg_column_types: column name → Postgres udt_name) restores them; a column the catalog doesn't know, such as an
    alias, stays a string. The REST API has no bind parameters, so $n are inlined as literals (_literal)."""
    def __init__(self, rest_url: str, api_key: str, org_id: str, datasource: str, http: httpx.AsyncClient,
                 column_types: Mapping[str, str], *, row_limit: int = 1_000_000, poll_s: float = 0.25) -> None:
        self._url = rest_url.rstrip("/") + "/sql-editor/sqls/run"
        self._headers = {"Authorization": f"Bearer {api_key}", "X-Org-ID": org_id}
        self._datasource, self._http, self._types = datasource, http, column_types
        self._row_limit, self._poll_s = row_limit, poll_s

    def table(self, name: str) -> str:
        return f"{self._datasource}.{name}"

    async def fetch(self, sql: str, params: Sequence[Any] = ()) -> list[Row]:
        text = _PARAM.sub(lambda m: _literal(params[int(m.group(1)) - 1]), sql) if params else sql
        log.info("zetaris sql: %s", text)
        try:
            resp = await self._http.post(self._url, headers={**self._headers, "X-Request-ID": str(uuid.uuid4())},
                                         json={"queryId": str(uuid.uuid4()), "sql": text, "source": "SqlEditor",
                                               "limit": self._row_limit}, timeout=120)
        except httpx.HTTPError as e:
            raise ZetarisError(f"cannot reach Zetaris at {self._url}: {e}") from e
        if resp.status_code != 200:
            raise ZetarisError(f"HTTP {resp.status_code}: {_message(resp)}")
        body = resp.json()
        headers = body.get("headers") or []
        return [{h: _value(self._types.get(h), v) for h, v in zip(headers, row)} for row in body.get("data") or []]

    async def wait_visible(self, sql, params, *, expect_rows, timeout_s):
        deadline = time.monotonic() + timeout_s
        while True:
            rows = await self.fetch(sql, params)
            if len(rows) == expect_rows:
                return rows
            if time.monotonic() >= deadline:
                raise NotYetVisible(f"{len(rows)} of {expect_rows} rows visible after {timeout_s}s")
            await asyncio.sleep(self._poll_s)


async def pg_column_types(pool) -> dict[str, str]:
    """Column name → Postgres udt_name over our public tables, for ZetarisReader. Agents read no column whose name
    has two types (only `at`, on the trace and World Model log tables, does)."""
    rows = await pool.fetch("SELECT DISTINCT column_name, udt_name FROM information_schema.columns "
                            "WHERE table_schema = 'public'")
    return {r["column_name"]: r["udt_name"] for r in rows}


class ZetarisError(Exception): ...


class NotYetVisible(Exception): ...


log = logging.getLogger("app.zetaris")
_PARAM = re.compile(r"\$(\d+)")


def _literal(v: Any) -> str:
    """A Spark SQL literal. Spark reads 'It''s' as two adjacent literals ("Its"), so quotes and backslashes are
    backslash-escaped instead (checked against the local Zetaris 2026-10-25)."""
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, datetime):
        return f"TIMESTAMP '{v.astimezone(timezone.utc).replace(tzinfo=None).isoformat(sep=' ')}'"
    if isinstance(v, date):
        return f"DATE '{v.isoformat()}'"
    if isinstance(v, str):
        return "'" + v.replace("\\", "\\\\").replace("'", "\\'") + "'"
    raise TypeError(f"no safe Zetaris literal for {type(v).__name__}")


def _value(udt: str | None, v: str | None) -> Any:
    if v is None or udt is None:
        return v
    if udt in ("int2", "int4", "int8"):
        return int(v)
    if udt in ("float4", "float8", "numeric"):
        return float(v)
    if udt == "bool":
        return v == "true"
    if udt == "date":
        return date.fromisoformat(v)
    if udt in ("timestamptz", "timestamp"):   # Zetaris renders timestamps in GMT without an offset
        return datetime.fromisoformat(v).replace(tzinfo=timezone.utc)
    if udt in ("json", "jsonb"):
        return json.loads(v)
    if udt == "_text":
        return _pg_array(v)
    return v


def _pg_array(text: str) -> list[str | None]:
    """A one-dimensional Postgres array literal, e.g. {plain,"with space","a \\"q\\"",NULL}."""
    items: list[str | None] = []
    i, body = 0, text[1:-1]
    while i < len(body):
        if body[i] == '"':
            i, buf = i + 1, []
            while body[i] != '"':
                if body[i] == "\\":
                    i += 1
                buf.append(body[i])
                i += 1
            items.append("".join(buf))
            i += 1
        else:
            end = body.find(",", i)
            end = len(body) if end == -1 else end
            word = body[i:end]
            items.append(None if word == "NULL" else word)
            i = end
        i += 1   # the comma
    return items


def _message(resp: httpx.Response) -> str:
    try:
        return str(resp.json().get("msg", resp.text))[:500]
    except ValueError:
        return resp.text[:500]
