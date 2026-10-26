"""Letter review skipped, for tests about what happens before or after it: a letter's drafted Facts park for review
(ADR 0006), and these commit them as read ("Use all as read"), none checked."""
from __future__ import annotations

from app import record


async def as_read(ctx, outcome: record.IngestOutcome) -> record.IngestOutcome:
    """A letter run parked for Letter review, committed with every drafted Fact as read; any other outcome as it is."""
    if isinstance(outcome, record.AwaitingReview):
        return (await record.commit_review(ctx, outcome.run_id, use_all_as_read=True)).committed
    return outcome


async def ingest_as_read(ctx, document_hash) -> record.IngestOutcome:
    """record.ingest, with Letter review skipped."""
    return await as_read(ctx, await record.ingest(ctx, document_hash))


async def confirm_as_read(ctx, run_id, resolutions) -> record.IngestOutcome:
    """record.confirm, with the Letter review that follows a letter's resolved Conflicts skipped."""
    return await as_read(ctx, await record.confirm(ctx, run_id, resolutions))


async def use_all_as_read(http, run_id: str) -> dict:
    """Over HTTP: skip a parked run's Letter review (if it is parked for one), then the run as GET /runs/{id} shows it."""
    run = (await http.get(f"/api/runs/{run_id}")).json()
    if run["state"]["phase"] == "awaiting_review":
        used = await http.post(f"/api/runs/{run_id}/review/use-all-as-read")
        assert used.status_code == 202, used.text
        run = (await http.get(f"/api/runs/{run_id}")).json()
    return run
