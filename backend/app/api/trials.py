"""Trials stored from the Australia ingest, and a screen of one letter against a named trial."""
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query

from app import llm, matching, record, trials
from app.api.deps import get_ctx
from app.api.schemas import (ClosedTrialListOut, ClosedTrialOut, ContactOut, CriterionMissOut, CriterionScreenOut,
                             MatchingTrialsOut, OutcomeSummaryOut, OutcomesOut, PublicationOut, ScreenIn,
                             TrialAskCitationOut, TrialAskIn, TrialAskOut, TrialDetailOut, TrialScreenOut, TrialSiteOut,
                             WashoutOut)
from app.ctx import Ctx

router = APIRouter(tags=["trials"])


def _listed(t: trials.Trial) -> ClosedTrialOut:
    return ClosedTrialOut(nct_id=t.nct_id, title=t.title, status=t.status, conditions=list(t.conditions),
                          closed_on=t.closed_on, url=trials.page_url(t.nct_id))


@router.get("/trials/matching", response_model=MatchingTrialsOut)
async def matching_trials(q: list[str] = Query(), ctx: Ctx = Depends(get_ctx)):
    """Stored Australian trials whose Condition labels contain one of these phrases as whole words."""
    phrases = [" ".join(phrase.split()) for phrase in q if phrase.strip()]
    if not phrases:
        raise HTTPException(422, "name the condition to search")
    labels = await trials.search_condition_labels(ctx, phrases, limit=200)
    open_trials, closed = await trials.trials_for_labels(ctx, tuple(one.label for one in labels))
    return MatchingTrialsOut(labels=[one.label for one in labels], open=[_listed(t) for t in open_trials],
                             closed=[_listed(t) for t in closed])


@router.get("/patients/{pid}/closed-trials", response_model=ClosedTrialListOut)
async def closed_trials(pid: str, ctx: Ctx = Depends(get_ctx)):
    """Closed trials listing one of the patient's Condition term labels, newest first; none before some are ticked."""
    term = (await record.diagnosis_step(ctx, record.PatientId(pid))).condition_term
    return ClosedTrialListOut(condition_term=term, trials=[ClosedTrialOut(
        nct_id=t.nct_id, title=t.title, status=t.status, conditions=list(t.conditions), closed_on=t.closed_on,
        url=trials.page_url(t.nct_id)) for t in await trials.closed_trials_with_labels(ctx, term)])


@router.post("/patients/{pid}/trials/{nct}/ask", response_model=TrialAskOut)
async def ask_trial(pid: str, nct: str, body: TrialAskIn, ctx: Ctx = Depends(get_ctx)):
    """One question about one stored trial. Criteria and letter regions are read through the agent reader."""
    question = " ".join(body.question.split())
    if not question:
        raise HTTPException(422, "the question is empty")
    if len(question) > 500:
        raise HTTPException(422, "the question is longer than 500 characters")
    try:
        asked = await matching.ask_trial(ctx, pid, nct, question)
    except record.NotFound as e:
        raise HTTPException(404, str(e)) from e
    except llm.LlmUnavailable as e:
        raise HTTPException(503, str(e)) from e
    def cited(c) -> TrialAskCitationOut:
        return TrialAskCitationOut(
            span_id=c.span_id, document_hash=c.document_hash, filename=c.filename, page=c.page,
            quote=c.quote, x0=c.x0, y0=c.y0, x1=c.x1, y1=c.y1)
    by_span = {c.span_id: c for c in asked.citations}
    return TrialAskOut(
        nct_id=asked.nct_id, title=asked.title, question=asked.question, standing=asked.standing,
        answer=asked.answer, to_gather=list(asked.to_gather), via=asked.via,
        citations=[cited(c) for c in asked.citations],
        misses=[CriterionMissOut(criterion_id=m.criterion_id, clause=m.clause, why=m.why, citation=cited(m.citation))
                for m in asked.misses],
        washouts=[WashoutOut(
            criterion_id=w.criterion_id, clause=w.clause, window_days=w.window_days, last_on=w.last_on.isoformat(),
            days_before=w.days_before, span_id=w.span_id, page=by_span[w.span_id].page, quote=by_span[w.span_id].quote,
            cleared=w.cleared,
        ) for w in asked.washouts if w.span_id in by_span])


@router.post("/patients/{pid}/trials/screen", response_model=list[TrialScreenOut])
async def screen_trials(pid: str, body: ScreenIn, ctx: Ctx = Depends(get_ctx)):
    """Judge these stored trials' criteria against the patient's letter. Each decisive answer names a region."""
    if not body.nct_ids:
        raise HTTPException(422, "name the trials to screen")
    if len(body.nct_ids) > 5:
        raise HTTPException(422, "screen at most 5 trials at a time")
    try:
        screens = await matching.screen_letter(ctx, pid, body.nct_ids)
    except llm.LlmUnavailable as e:
        raise HTTPException(503, str(e)) from e
    return [TrialScreenOut(
        nct_id=screen.nct_id, title=screen.title, outcome=screen.outcome,
        criteria=[CriterionScreenOut(
            criterion_id=row.criterion_id, kind=row.kind, text=row.text, outcome=row.outcome,
            rationale=row.rationale, span_id=row.span_id, page=row.page, quote=row.quote,
            x0=row.x0, y0=row.y0, x1=row.x1, y1=row.y1,
        ) for row in screen.criteria],
    ) for screen in screens]


@router.get("/trials")
async def list_trials(): raise NotImplementedError


@router.get("/trials/{nct}", response_model=TrialDetailOut)
async def get_trial(nct: str, ctx: Ctx = Depends(get_ctx)):
    """The Trial, who to contact about it (#27) and its Outcomes (#25)."""
    nct_id = trials.NctId(nct)
    t, c, o = await trials.trial(ctx, nct_id), await trials.contacts(ctx, nct_id), await trials.outcomes(ctx, nct_id)
    if t is None or c is None or o is None:
        raise HTTPException(404, f"no Trial {nct}")
    return TrialDetailOut(
        nct_id=t.nct_id, title=t.title, status=t.status, page_url=c.page_url, sponsor=c.sponsor,
        responsible_party=_contact_out(c.responsible_party) if c.responsible_party else None,
        central_contacts=[_contact_out(x) for x in c.central], overall_officials=[_contact_out(x) for x in c.officials],
        sites=[TrialSiteOut(facility=s.facility, city=s.city, status=s.status,
                            contacts=[_contact_out(x) for x in s.contacts]) for s in await trials.sites(ctx, nct_id)],
        outcomes=OutcomesOut(**{**asdict(o), "publications": [PublicationOut(**asdict(p), url=p.url)
                                                             for p in o.publications]}))


@router.get("/trials/{nct}/outcomes/summary", response_model=OutcomeSummaryOut)
async def outcome_summary(nct: str, ctx: Ctx = Depends(get_ctx)):
    """A plain-language summary of the Trial's Outcomes (#26), written by the model on the first ask and reused while
    the Outcomes are unchanged. 404: unknown Trial; 503: model unavailable (nothing is cached, so a retry asks again)."""
    try:
        s = await trials.outcome_summary(ctx, trials.NctId(nct))
    except llm.LlmUnavailable as err:
        raise HTTPException(503, str(err))
    if s is None:
        raise HTTPException(404, f"no Trial {nct}")
    return OutcomeSummaryOut(nct_id=nct, summary=s.text)


def _contact_out(c: trials.Contact) -> ContactOut:
    return ContactOut(**asdict(c))
