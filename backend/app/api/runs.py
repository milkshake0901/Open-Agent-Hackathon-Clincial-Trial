"""Runs and traces: how the system reasoned, and the patient's answer to a Conflict."""
from dataclasses import asdict

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from app import matching, record, trace
from app.api.deps import get_ctx
from app.api.schemas import (
    ConfirmIn, ConflictOut, ConflictSideOut, ConflictsOut, DocumentDateIn, IngestOutcomeOut, LetterReviewOut,
    RescanSummary, ReviewAnswerIn, ReviewFactOut, ReviewRegionOut,
)
from app.ctx import Ctx
from app.trace.state import IngestRunState, reduce_ingest

router = APIRouter(tags=["runs"])


async def _read(ctx: Ctx, run_id: str, since: int = 0) -> trace.RunLog:
    return await trace.read(ctx.ui_reader, trace.RunId(run_id), since_seq=since)


def _events(log: trace.RunLog) -> list[dict]:
    return [{"seq": e.seq, "at": e.at, "kind": e.event.kind, "actor": e.actor, "causation_id": e.causation_id,
             "payload": e.event.model_dump(mode="json")} for e in log.events]


@router.get("/runs/{run_id}")
async def get_run(run_id: str, ctx: Ctx = Depends(get_ctx)):
    """{run_id, kind, head, state, events}. An ingest run's state.phase is started | drafting | awaiting_patient |
    awaiting_review | committed | rejected; the page adding Documents polls this until every run it started has ended."""
    log = await _read(ctx, run_id)
    state = None
    if log.kind == "ingest":
        folded = IngestRunState()
        for e in log.events:
            folded = reduce_ingest(folded, e.event)
        state = asdict(folded)
    return {"run_id": log.run_id, "kind": log.kind, "head": log.head, "state": state, "events": _events(log)}


@router.get("/runs/{run_id}/events")
async def run_events(run_id: str, since: int = 0, ctx: Ctx = Depends(get_ctx)):
    """Polled about once a second by the trace page while a run is live."""
    log = await _read(ctx, run_id, since)
    return {"head": log.head, "events": _events(log)}


async def _side(ctx: Ctx, h: str, page: int, quote: str, value: str, unit: str | None, observed_on,
                question: str | None) -> ConflictSideOut:
    doc = await record.document(ctx, record.DocumentHash(h))
    text = next((p.text for p in doc.pages if p.number == page), "")
    label = f"Patient-reported, intake questionnaire, {question}" if question else f"{doc.filename}, page {page}"
    return ConflictSideOut(document_hash=h, filename=doc.filename, page=page, page_text=text, quote=quote, value=value,
                           unit=unit, observed_on=observed_on, label=label)


async def _conflict_out(ctx: Ctx, c: record.Conflict) -> ConflictOut:
    d, a = c.draft, c.accepted
    return ConflictOut(
        id=c.id, message=c.message,
        draft=await _side(ctx, c.document_hash, d.page, d.quote, d.value, d.unit, d.observed_on, d.question),
        accepted=a and await _side(ctx, a.document_hash, a.page, a.quote, a.value, a.unit, a.observed_on, a.question))


@router.get("/runs/{run_id}/conflicts", response_model=ConflictsOut)
async def conflicts(run_id: str, ctx: Ctx = Depends(get_ctx)):
    """The Conflicts a parked ingest run waits on, each side with its Document, page and quote (the Conflict dialog)."""
    found = await record.conflicts(ctx, trace.RunId(run_id))
    return ConflictsOut(run_id=run_id, conflicts=[await _conflict_out(ctx, c) for c in found])


def outcome_out(outcome: record.IngestOutcome) -> IngestOutcomeOut:
    match outcome:
        case record.Committed(run_id=run_id, version=v):
            return IngestOutcomeOut(run_id=run_id, outcome="committed", document_hash=v.document_hash,
                                      profile_version_id=v.id, version_number=v.number)
        case record.AwaitingPatient(run_id=run_id):
            return IngestOutcomeOut(run_id=run_id, outcome="awaiting_patient")
        case record.AwaitingReview(run_id=run_id):
            return IngestOutcomeOut(run_id=run_id, outcome="awaiting_review")
        case record.Rejected(run_id=run_id, reason=reason):
            return IngestOutcomeOut(run_id=run_id, outcome="rejected", reason=reason)


@router.post("/runs/{run_id}/confirm", status_code=202, response_model=IngestOutcomeOut)
async def confirm(run_id: str, body: ConfirmIn, ctx: Ctx = Depends(get_ctx)):
    """Patient resolves Conflicts on a parked ingest run → record.confirm. Committed re-scans the new version under
    the run's correlation id, as an added Document does. 404 unknown run, 409 not awaiting the patient, 422 unknown Conflict."""
    try:
        outcome = await record.confirm(ctx, trace.RunId(run_id), [
            record.Resolution(record.ConflictId(r.conflict_id), r.choice) for r in body.resolutions])
    except record.NotAwaitingPatient as e:
        raise HTTPException(409, str(e))
    except record.InvalidResolution as e:
        raise HTTPException(422, str(e))
    accepted = outcome_out(outcome)
    if isinstance(outcome, record.Committed):
        accepted.rescan = RescanSummary.of(await matching.rescan(ctx, outcome.version.id, correlation_id=outcome.run_id))
    return accepted


def _review_out(r: record.LetterReview) -> LetterReviewOut:
    def fact(it: record.ReviewItem) -> ReviewFactOut:
        d, g = it.draft, it.region
        return ReviewFactOut(
            index=it.index, resource=d.resource, subject=d.subject, value=d.value, unit=d.unit,
            observed_on=d.observed_on, page=d.page, quote=d.quote,
            region=g and ReviewRegionOut(span_id=g.span_id, kind=g.kind, text=g.text, x0=g.x0, y0=g.y0, x1=g.x1,
                                         y1=g.y1),
            flags=list(d.flags), flagged=d.flagged, decision=it.decision, correction=it.correction)
    return LetterReviewOut(run_id=r.run_id, document_hash=r.document.hash, filename=r.document.filename,
                           page_count=len(r.document.pages), document_date=r.document_date,
                           document_date_corrected=r.document_date_corrected, date_order=r.date_order,
                           facts=[fact(it) for it in r.items])


async def _reviewing(call) -> LetterReviewOut:
    try:
        return _review_out(await call)
    except record.NotAwaitingReview as e:
        raise HTTPException(409, str(e))
    except record.InvalidReview as e:
        raise HTTPException(422, str(e))


@router.get("/runs/{run_id}/review", response_model=LetterReviewOut)
async def letter_review(run_id: str, ctx: Ctx = Depends(get_ctx)):
    """Letter review: the drafted Facts a letter's run waits on, each with its Region (page image box), flags and
    the Respondent's answer so far; flagged first. 404 unknown run, 409 not awaiting review."""
    return await _reviewing(record.letter_review(ctx, trace.RunId(run_id)))


@router.post("/runs/{run_id}/review/facts/{index}", response_model=LetterReviewOut)
async def answer_review(run_id: str, index: int, body: ReviewAnswerIn, ctx: Ctx = Depends(get_ctx)):
    """Keep ("Looks right") or drop ("Not right", with an optional correction) one drafted Fact. 422: no such Fact, or a
    correction on a kept one."""
    return await _reviewing(record.answer_review(ctx, trace.RunId(run_id), index, body.decision, body.correction))


@router.put("/runs/{run_id}/review/document-date", response_model=LetterReviewOut)
async def correct_document_date(run_id: str, body: DocumentDateIn, ctx: Ctx = Depends(get_ctx)):
    """Correct the letter's Document date; the drafts it dated follow it. 422: a date after today."""
    return await _reviewing(record.correct_document_date(ctx, trace.RunId(run_id), body.document_date))


async def _commit_review(ctx: Ctx, background: BackgroundTasks, run_id: str, use_all_as_read: bool) -> IngestOutcomeOut:
    from app.api.documents import start_ingest

    try:
        reviewed = await record.commit_review(ctx, trace.RunId(run_id), use_all_as_read=use_all_as_read)
    except record.NotAwaitingReview as e:
        raise HTTPException(409, str(e))
    out = outcome_out(reviewed.committed)
    version = reviewed.committed.version
    if reviewed.corrections is None:
        background.add_task(matching.rescan, ctx, version.id, correlation_id=reviewed.committed.run_id)
    else:   # the corrections' version is re-scanned when it commits; the letter's, if they do not
        out.correction_run_id = await start_ingest(ctx, background, reviewed.corrections, otherwise=version.id)
    return out


@router.post("/runs/{run_id}/review/commit", status_code=202, response_model=IngestOutcomeOut)
async def commit_review(run_id: str, background: BackgroundTasks, ctx: Ctx = Depends(get_ctx)):
    """Commit the reviewed letter: kept Facts checked, unanswered ones not checked, dropped ones never. The
    corrections become an answer in the Respondent's questionnaire, ingested in the background (correction_run_id);
    the Re-scan follows the last commit. 404 unknown run, 409 not awaiting review."""
    return await _commit_review(ctx, background, run_id, use_all_as_read=False)


@router.post("/runs/{run_id}/review/use-all-as-read", status_code=202, response_model=IngestOutcomeOut)
async def use_all_as_read(run_id: str, background: BackgroundTasks, ctx: Ctx = Depends(get_ctx)):
    """Skip the review: commit every drafted Fact as read, none checked; then Re-scan in the background."""
    return await _commit_review(ctx, background, run_id, use_all_as_read=True)


@router.get("/traces/{correlation_id}")
async def trace_tree(correlation_id: str):
    """Causal tree across the ingest and its Re-scan, joined with llm_call (requested vs answered model)."""
    raise NotImplementedError
