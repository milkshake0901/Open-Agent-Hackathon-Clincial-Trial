"""ZetarisReader against a fake Zetaris REST API (httpx.MockTransport): the SQL it sends, the rows it gives back.

Zetaris answers {headers, data, total, timeUsed} with every non-null value as a string, so the reader restores types
from the Postgres catalog by the tables the query reads and their column names. The shapes and escaping rules here were checked against the local Zetaris
on 2026-10-25 (see the live comparison in test_zetaris_live.py).
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone

import httpx
import pytest

from app.sql.reader import NotYetVisible, ZetarisError, ZetarisReader

TYPES = {"trial": {"nct_id": "text", "conditions": "_text", "has_results": "bool", "completion_date": "date",
                   "fetched_at": "timestamptz"},
         "trial_site": {"nct_id": "text", "ordinal": "int4", "lat": "float8"},
         "trace_event": {"tables_json": "jsonb", "at": "timestamptz"},
         "wm_event": {"number": "int8", "at": "text"}}


def reader(handler, **kw) -> ZetarisReader:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return ZetarisReader("http://zetaris.test/api/v1.0", "key-123", "1", "trialmatch", http, TYPES, **kw)


def answer(headers, *rows):
    return lambda request: httpx.Response(200, json={"headers": headers, "data": [list(r) for r in rows],
                                                     "total": len(rows), "timeUsed": 3})


async def test_a_query_is_posted_to_the_sql_editor_with_the_api_key_and_a_fresh_request_id_each_time():
    seen = []

    def handler(request):
        seen.append(request)
        return answer(["n"], ["1"])(request)

    r = reader(handler)
    await r.fetch("SELECT 1 AS n")
    await r.fetch("SELECT 1 AS n")

    first = seen[0]
    assert first.method == "POST" and str(first.url) == "http://zetaris.test/api/v1.0/sql-editor/sqls/run"
    assert first.headers["Authorization"] == "Bearer key-123" and first.headers["X-Org-ID"] == "1"
    body = json.loads(first.content)
    assert body["sql"] == "SELECT 1 AS n" and body["source"] == "SqlEditor" and body["limit"] > 10_000
    assert seen[0].headers["X-Request-ID"] != seen[1].headers["X-Request-ID"]
    assert json.loads(seen[0].content)["queryId"] != json.loads(seen[1].content)["queryId"]


async def test_tables_are_qualified_by_the_datasource_our_postgres_is_registered_under():
    assert reader(answer([])).table("fact") == "trialmatch.fact"


async def test_rows_come_back_keyed_by_column_with_their_postgres_types_restored():
    r = reader(answer(
        ["nct_id", "conditions", "ordinal", "has_results", "lat", "completion_date", "fetched_at", "tables_json", "n"],
        ["NCT01056354", '{"Influenza and Other Novel Respiratory Viruses",Obesity}', "3", "false", "-33.86",
         "2017-05-12", "2026-10-25 01:54:18.262505", '[{"rows": [[1]]}]', "7"],
        ["NCT07220642", "{}", None, "true", None, None, "2026-10-25 01:54:18", None, None]))

    first, second = await r.fetch("SELECT ... FROM trialmatch.trial t JOIN trialmatch.trial_site s ON ... "
                                  "JOIN trialmatch.trace_event e ON ...")

    assert first == {"nct_id": "NCT01056354", "conditions": ["Influenza and Other Novel Respiratory Viruses", "Obesity"],
                     "ordinal": 3, "has_results": False, "lat": -33.86, "completion_date": date(2017, 5, 12),
                     "fetched_at": datetime(2026, 10, 25, 1, 54, 18, 262505, tzinfo=timezone.utc),
                     "tables_json": [{"rows": [[1]]}], "n": "7"}   # an alias the catalog doesn't know stays a string
    assert second["conditions"] == [] and second["ordinal"] is None and second["has_results"] is True
    assert second["fetched_at"] == datetime(2026, 10, 25, 1, 54, 18, tzinfo=timezone.utc)


async def test_a_column_name_two_tables_type_differently_is_typed_by_the_table_the_query_reads():
    sent = answer(["at"], ["2026-10-25 01:54:18"])

    [from_trace] = await reader(sent).fetch("SELECT at FROM trialmatch.trace_event WHERE run_id = $1", ("r",))
    [from_log] = await reader(sent).fetch("SELECT at FROM trialmatch.wm_event")
    [unread] = await reader(sent).fetch("SELECT 1 AS at")

    assert from_trace["at"] == datetime(2026, 10, 25, 1, 54, 18, tzinfo=timezone.utc)
    assert from_log["at"] == unread["at"] == "2026-10-25 01:54:18"


@pytest.mark.parametrize("literal, items", [
    ('{plain,"with space","a \\"quote\\"","back\\\\slash",NULL,"NULL"}',
     ["plain", "with space", 'a "quote"', "back\\slash", None, "NULL"]),
    ('{"comma, inside",x}', ["comma, inside", "x"]),
])
async def test_postgres_text_arrays_are_parsed_including_quotes_escapes_and_nulls(literal, items):
    rows = await reader(answer(["conditions"], [literal])).fetch("SELECT conditions FROM trialmatch.trial")
    assert rows[0]["conditions"] == items


async def test_parameters_are_inlined_as_literals_spark_reads_back_exactly():
    sent = []

    def handler(request):
        sent.append(json.loads(request.content)["sql"])
        return answer([])(request)

    await reader(handler).fetch(
        "SELECT * FROM t WHERE a = $1 AND b = $2 AND c = $3 AND d = $4 AND e = $5 AND f = $6 AND g = $10 OR h = $1",
        ("NCT0'1\\x", 7, 2.5, True, date(2020, 1, 2), None, "", "", "", "ten"))

    # Spark reads '' as two adjacent literals ('It''s' → Its), so quotes and backslashes are backslash-escaped.
    assert sent == ["SELECT * FROM t WHERE a = 'NCT0\\'1\\\\x' AND b = 7 AND c = 2.5 AND d = TRUE "
                    "AND e = DATE '2020-01-02' AND f = NULL AND g = 'ten' OR h = 'NCT0\\'1\\\\x'"]


async def test_a_parameter_of_a_type_with_no_safe_literal_is_refused_before_anything_is_sent():
    def handler(request):
        raise AssertionError("nothing should be sent")

    with pytest.raises(TypeError):
        await reader(handler).fetch("SELECT * FROM t WHERE a = $1", ([1, 2],))


async def test_a_zetaris_error_carries_its_message():
    r = reader(lambda request: httpx.Response(400, json={"msg": "[TABLE_OR_VIEW_NOT_FOUND] trialmatch.nope"}))

    with pytest.raises(ZetarisError, match="TABLE_OR_VIEW_NOT_FOUND"):
        await r.fetch("SELECT * FROM trialmatch.nope")


async def test_an_unreachable_zetaris_is_a_zetaris_error():
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(ZetarisError, match="reach"):
        await reader(handler).fetch("SELECT 1")


async def test_wait_visible_polls_until_the_expected_rows_appear():
    calls = []

    def handler(request):
        calls.append(1)
        return answer(["nct_id"], *([["NCT1"]] if len(calls) >= 3 else []))(request)

    rows = await reader(handler, poll_s=0).wait_visible("SELECT nct_id FROM t", (), expect_rows=1, timeout_s=5)

    assert rows == [{"nct_id": "NCT1"}] and len(calls) == 3


async def test_wait_visible_gives_up_with_not_yet_visible_once_the_bound_elapses():
    with pytest.raises(NotYetVisible):
        await reader(answer(["nct_id"]), poll_s=0).wait_visible("SELECT nct_id FROM t", (), expect_rows=1,
                                                                timeout_s=0.05)


async def test_every_query_writes_a_zetaris_sql_line_to_the_log_file(tmp_path):
    from app import logfile
    path = tmp_path / "trialmatch.jsonl"
    logfile.configure(path)
    try:
        await reader(answer(["n"], ["1"], ["2"])).fetch("SELECT n FROM t WHERE nct_id = $1", ("NCT1",))
    finally:
        logfile.reset()

    [line] = [json.loads(x) for x in path.read_text().splitlines()]
    assert line["step"] == "zetaris.sql" and line["logger"] == "app.zetaris"
    assert line["sql"] == "SELECT n FROM t WHERE nct_id = 'NCT1'" and line["rows"] == 2
    assert isinstance(line["duration_ms"], int)
