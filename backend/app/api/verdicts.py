"""Verdicts, why they changed, and Doctor questions."""
from fastapi import APIRouter, Depends, HTTPException, Query

from app import matching, record, trials
from app.api.deps import get_ctx
from app.api.schemas import DoctorQuestionOut, RescanOut, VerdictChangeOut, VerdictListOut, VerdictOut
from app.ctx import Ctx

router = APIRouter(tags=["verdicts"])


async def _version(ctx: Ctx, pid: str, vid: str) -> record.ProfileVersion:
    try:
        v = await record.profile_version(ctx, record.ProfileVersionId(vid))
    except record.NotFound as e:
        raise HTTPException(404, str(e))
    if v.patient_id != pid:
        raise HTTPException(404, f"profile version {vid}")
    return v


def citation_label(question: str | None, page: int) -> str:
    return f"Patient-reported, intake questionnaire, {question}" if question else f"page {page}"


def question_out(q: matching.DoctorQuestion) -> DoctorQuestionOut:
    return DoctorQuestionOut(criterion_id=q.criterion_id, nct_id=q.nct_id, subject=q.subject, text=q.text,
                             unblocks=list(q.unblocks))


def citation_out(c: matching.Citation | None) -> dict | None:
    return None if c is None else {
        "fact_id": c.fact_id, "document_hash": c.document_hash, "page": c.page, "quote": c.quote,
        "question": c.question, "label": citation_label(c.question, c.page)}


def change_out(ch: matching.VerdictChange) -> VerdictChangeOut:
    return VerdictChangeOut(nct_id=ch.nct_id, outcome_from=ch.outcome_from, outcome_to=ch.outcome_to,
                            criteria_changed=[{"criterion_id": c.criterion_id, "text": c.text,
                                               "outcome_from": c.outcome_from, "outcome_to": c.outcome_to,
                                               "citation": citation_out(c.citation)} for c in ch.criteria_changed])


async def verdicts_changed(ctx: Ctx, from_version: str, to_version: str) -> list[VerdictChangeOut]:
    out = []
    for v in await matching.verdicts_for_version(ctx, record.ProfileVersionId(to_version)):
        ch = await matching.change_between(ctx, v.nct_id, record.ProfileVersionId(from_version), v.profile_version_id)
        if ch.outcome_from != ch.outcome_to or ch.criteria_changed:
            out.append(change_out(ch))
    return out


async def _verdict_out(ctx: Ctx, v: matching.Verdict) -> VerdictOut:
    trial = await trials.trial(ctx, v.nct_id)
    criteria = {c.id: c for c in await trials.criteria(ctx, v.nct_id)}
    return VerdictOut(
        nct_id=v.nct_id, title=trial.title if trial else v.nct_id, status=trial.status if trial else "",
        profile_version_id=v.profile_version_id, outcome=v.outcome, degraded=v.degraded, attempts=v.attempts,
        results=[{"criterion_id": r.criterion_id, "kind": criteria[r.criterion_id].kind,
                  "text": criteria[r.criterion_id].text, "outcome": r.outcome, "rationale": r.rationale,
                  "citation": citation_out(r.citation)}
                 for r in v.results],
        questions=[question_out(q) for q in v.questions])


@router.post("/patients/{pid}/versions/{vid}/rescan", status_code=202, response_model=RescanOut)
async def rescan(pid: str, vid: str, ctx: Ctx = Depends(get_ctx)):
    """Idempotent: finishes immediately with everything skipped if nothing changed. Runs inline."""
    await _version(ctx, pid, vid)
    r = await matching.rescan(ctx, record.ProfileVersionId(vid))
    return RescanOut(run_id=r.run_id, planned=list(r.planned), judged=list(r.judged),
                     skipped_existing=list(r.skipped_existing), failed=[list(f) for f in r.failed])


@router.get("/patients/{pid}/versions/{vid}/verdicts", response_model=VerdictListOut)
async def list_verdicts(pid: str, vid: str, ctx: Ctx = Depends(get_ctx)):
    """Ranked: eligible, then possible (fewest unknowns first), then excluded."""
    await _version(ctx, pid, vid)
    verdicts = await matching.verdicts_for_version(ctx, record.ProfileVersionId(vid))
    return VerdictListOut(profile_version_id=vid, verdicts=[await _verdict_out(ctx, v) for v in verdicts])


@router.get("/patients/{pid}/versions/{vid}/verdicts/{nct}", response_model=VerdictOut)
async def get_verdict(pid: str, vid: str, nct: str, ctx: Ctx = Depends(get_ctx)):
    await _version(ctx, pid, vid)
    v = await matching.verdict(ctx, trials.NctId(nct), record.ProfileVersionId(vid))
    if v is None:
        raise HTTPException(404, f"no Verdict for {nct} at {vid}")
    return await _verdict_out(ctx, v)


@router.get("/patients/{pid}/versions/{vid}/verdicts/{nct}/change", response_model=VerdictChangeOut)
async def verdict_change(pid: str, vid: str, nct: str, from_: str = Query(alias="from"),
                         ctx: Ctx = Depends(get_ctx)):
    await _version(ctx, pid, vid)
    await _version(ctx, pid, from_)
    try:
        return change_out(await matching.change_between(ctx, trials.NctId(nct), record.ProfileVersionId(from_),
                                                        record.ProfileVersionId(vid)))
    except LookupError as e:
        raise HTTPException(404, str(e))


@router.get("/patients/{pid}/questions", response_model=list[DoctorQuestionOut])
async def doctor_questions(pid: str, version: str, ctx: Ctx = Depends(get_ctx)):
    """Deduplicated across Trials; each names the Trials it would help decide."""
    await _version(ctx, pid, version)
    return [question_out(q) for q in await matching.questions_for_version(ctx, record.ProfileVersionId(version))]
