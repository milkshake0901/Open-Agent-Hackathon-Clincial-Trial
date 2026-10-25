"""The Australia-wide ingest (#22, ADR 0004) fed by the live ClinicalTrials.gov v2 API, paged by pageToken and
filtered to Australia. Recorded `GET /api/v2/studies` pages are served at the transport; no test reaches the API."""
from __future__ import annotations

import httpx
import pytest

from app import trials
from tests.trials.test_ingest import AU, site, study


def recorded(*pages, failures=None):
    """A transport serving `pages` (lists of studies) as `GET /api/v2/studies` bodies chained by nextPageToken.
    `failures` maps a page number to the responses (or exceptions) served before that page succeeds."""
    failures = {n: list(r) for n, r in (failures or {}).items()}
    seen: list[httpx.Request] = []

    def handle(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        token = req.url.params.get("pageToken")
        n = 1 if token is None else int(token.removeprefix("token-")) + 1
        if failures.get(n):
            failure = failures[n].pop(0)
            if isinstance(failure, Exception):
                raise failure
            return failure
        body = {"studies": list(pages[n - 1]), **({"nextPageToken": f"token-{n}"} if n < len(pages) else {})}
        return httpx.Response(200, json=body)

    return httpx.MockTransport(handle), seen


class Sleeps:
    """Stands in for asyncio.sleep so pacing and back-off are observed, not waited for."""
    def __init__(self):
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


async def test_the_live_source_pages_through_every_australian_study_by_page_token(ctx):
    transport, seen = recorded([study("NCT00000001", sites=[AU])],
                               [study("NCT00000002", sites=[site("Mayo Clinic", "Rochester", "United States")])],
                               [study("NCT00000003", status="NOT_YET_RECRUITING", sites=[AU])])

    report = await trials.ingest(ctx, trials.LivePages(transport=transport, sleep=Sleeps()))

    assert report.new == ("NCT00000001", "NCT00000003") and report.source == "http"
    assert [r.url.params.get("pageToken") for r in seen] == [None, "token-1", "token-2"]
    assert all(r.url.path == "/api/v2/studies" and r.url.params["query.locn"] == "Australia" for r in seen)
    assert [t.nct_id for t in await trials.active_trials(ctx)] == ["NCT00000001", "NCT00000003"]
    assert (await trials.trial(ctx, trials.NctId("NCT00000001"))).fetched_at == ctx.now().isoformat()


async def test_requests_are_spaced_to_stay_under_the_rate_limit(ctx):
    transport, seen = recorded(*([study(f"NCT0000000{n}", sites=[AU])] for n in range(1, 5)))
    sleeps = Sleeps()

    await trials.ingest(ctx, trials.LivePages(transport=transport, sleep=sleeps, requests_per_minute=40))

    assert len(seen) == 4
    assert len(sleeps.calls) == 3 and all(s > 1.4 for s in sleeps.calls)   # 60 s / 40 requests = 1.5 s apart


async def test_transient_failures_are_retried_and_the_ingest_completes(ctx):
    transport, seen = recorded([study("NCT00000001", sites=[AU])], [study("NCT00000002", sites=[AU])],
                               failures={2: [httpx.Response(503), httpx.ConnectError("reset"),
                                             httpx.Response(429, headers={"Retry-After": "7"})]})
    sleeps = Sleeps()

    report = await trials.ingest(ctx, trials.LivePages(transport=transport, sleep=sleeps))

    assert report.new == ("NCT00000001", "NCT00000002")
    assert [r.url.params.get("pageToken") for r in seen] == [None] + ["token-1"] * 4
    assert 7.0 in sleeps.calls


async def test_a_source_that_keeps_failing_raises_and_records_nothing(ctx):
    transport, seen = recorded([study("NCT00000001", sites=[AU])], [study("NCT00000002", sites=[AU])],
                               failures={2: [httpx.Response(502)] * 3})

    with pytest.raises(httpx.HTTPStatusError) as failed:
        await trials.ingest(ctx, trials.LivePages(transport=transport, sleep=Sleeps(), retries=2))

    assert failed.value.response.status_code == 502
    assert len(seen) == 4
    assert await trials.trial(ctx, trials.NctId("NCT00000001")) is None


async def test_a_rejected_request_is_not_retried(ctx):
    transport, seen = recorded([study("NCT00000001", sites=[AU])], failures={1: [httpx.Response(400)]})

    with pytest.raises(httpx.HTTPStatusError) as failed:
        await trials.ingest(ctx, trials.LivePages(transport=transport, sleep=Sleeps()))

    assert failed.value.response.status_code == 400
    assert len(seen) == 1
