"""Verdicts, why they changed, Doctor questions and Respondent questions."""
from fastapi import APIRouter, Depends, HTTPException, Query

from app import matching, record, trials
from app.api.deps import get_ctx, patient_version
from app.api.schemas import DoctorQuestionOut, RescanOut, RespondentQuestionOut, VerdictChangeOut, VerdictListOut, VerdictOut
from app.ctx import Ctx

router = APIRouter(tags=["verdicts"])


def citation_label(question: str | None, page: int) -> str:
    return f"Patient-reported, intake questionnaire, {question}" if question else f"page {page}"


def question_out(q: matching.DoctorQuestion) -> DoctorQuestionOut:
    return DoctorQuestionOut(criterion_id=q.criterion_id, nct_id=q.nct_id, subject=q.subject, text=q.text,
                             unblocks=list(q.unblocks))


def respondent_question_out(q: matching.RespondentQuestion) -> RespondentQuestionOut:
    return RespondentQuestionOut(criterion_id=q.criterion_id, nct_id=q.nct_id, question_id=q.question_id,
                                 question=q.question, subject=q.subject, text=q.text, unblocks=list(q.unblocks))


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
    for v in (await matching.verdicts_for_version(ctx, record.ProfileVersionId(to_version))).verdicts:
        ch = await matching.change_between(ctx, v.nct_id, record.ProfileVersionId(from_version), v.profile_version_id)
        if ch.outcome_from != ch.outcome_to or ch.criteria_changed:
            out.append(change_out(ch))
    return out


async def _verdict_out(ctx: Ctx, v: matching.Verdict) -> VerdictOut:
    trial = await trials.trial(ctx, v.nct_id)
    criteria = {c.id: c for c in await trials.criteria(ctx, v.nct_id)}
    return VerdictOut(
        nct_id=v.nct_id, title=trial.title if trial else v.nct_id, status=trial.status if trial else "",
        no_longer_recruiting=trial is None or not trial.is_open,
        profile_version_id=v.profile_version_id, outcome=v.outcome, degraded=v.degraded, attempts=v.attempts,
        results=[{"criterion_id": r.criterion_id, "kind": criteria[r.criterion_id].kind,
                  "text": criteria[r.criterion_id].text, "outcome": r.outcome, "rationale": r.rationale,
                  "citation": citation_out(r.citation)}
                 for r in v.results],
        questions=[question_out(q) for q in v.questions],
        respondent_questions=[respondent_question_out(q) for q in v.respondent_questions],
        nearest_site=_site_out(v.nearest_site) if v.nearest_site else None,
        sites=[_site_out(sd) for sd in v.sites[:SITES_LISTED]], further_away=v.further_away)


SITES_LISTED = 3


def _site_out(sd: matching.TrialSiteDistance) -> dict:
    return {"name": sd.name, "status": sd.status, "km": sd.km}


@router.post("/patients/{pid}/versions/{vid}/rescan", status_code=202, response_model=RescanOut)
async def rescan(pid: str, vid: str, ctx: Ctx = Depends(get_ctx)):
    """Idempotent: finishes immediately with everything skipped if nothing changed. Runs inline."""
    await patient_version(ctx, pid, vid)
    r = await matching.rescan(ctx, record.ProfileVersionId(vid))
    return RescanOut(run_id=r.run_id, planned=list(r.planned), judged=list(r.judged),
                     skipped_existing=list(r.skipped_existing), failed=[list(f) for f in r.failed])


@router.get("/patients/{pid}/versions/{vid}/verdicts", response_model=VerdictListOut)
async def list_verdicts(pid: str, vid: str, ctx: Ctx = Depends(get_ctx)):
    """Ranked: eligible, then possible (fewest unknowns first), then excluded. Only Trials the patient's Condition term
    selects; with none (the diagnosis step unfinished) `condition_term` is None and nothing is listed."""
    await patient_version(ctx, pid, vid)
    listed = await matching.verdicts_for_version(ctx, record.ProfileVersionId(vid))
    return VerdictListOut(profile_version_id=vid, condition_term=listed.condition_term,
                          verdicts=[await _verdict_out(ctx, v) for v in listed.verdicts])


@router.get("/patients/{pid}/versions/{vid}/verdicts/{nct}", response_model=VerdictOut)
async def get_verdict(pid: str, vid: str, nct: str, ctx: Ctx = Depends(get_ctx)):
    await patient_version(ctx, pid, vid)
    v = await matching.verdict(ctx, trials.NctId(nct), record.ProfileVersionId(vid))
    if v is None:
        raise HTTPException(404, f"no Verdict for {nct} at {vid}")
    return await _verdict_out(ctx, v)


@router.get("/patients/{pid}/versions/{vid}/verdicts/{nct}/change", response_model=VerdictChangeOut)
async def verdict_change(pid: str, vid: str, nct: str, from_: str = Query(alias="from"),
                         ctx: Ctx = Depends(get_ctx)):
    await patient_version(ctx, pid, vid)
    await patient_version(ctx, pid, from_)
    try:
        return change_out(await matching.change_between(ctx, trials.NctId(nct), record.ProfileVersionId(from_),
                                                        record.ProfileVersionId(vid)))
    except LookupError as e:
        raise HTTPException(404, str(e))


@router.get("/patients/{pid}/questions", response_model=list[DoctorQuestionOut])
async def doctor_questions(pid: str, version: str, ctx: Ctx = Depends(get_ctx)):
    """Deduplicated across Trials; each names the Trials it would help decide."""
    await patient_version(ctx, pid, version)
    return [question_out(q) for q in await matching.questions_for_version(ctx, record.ProfileVersionId(version))]


@router.get("/patients/{pid}/respondent-questions", response_model=list[RespondentQuestionOut])
async def respondent_questions(pid: str, version: str, ctx: Ctx = Depends(get_ctx)):
    """Deduplicated by questionnaire question; each names the Trials it would help decide. Answering is a
    questionnaire resubmission (POST /patients/{pid}/questionnaire)."""
    await patient_version(ctx, pid, version)
    return [respondent_question_out(q)
            for q in await matching.respondent_questions_for_version(ctx, record.ProfileVersionId(version))]
