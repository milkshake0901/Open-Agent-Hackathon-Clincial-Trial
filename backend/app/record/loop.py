"""app/record/loop.py — the Intake⇄Critic loop as a bounded state machine.

Transitions are a closed set; the attempt bound is a field; exhaustion is a transition.
Every step is appended to the run's trace, and a parked run (AwaitingPatient) is rehydrated
from those trace events on confirm(). Accepted Facts are committed through the World Model.
"""
from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, replace
from datetime import date
from typing import Awaitable, Callable

from app.ctx import Ctx
from app.llm import LlmUnavailable
from app.record import critic, dates, intake, questionnaire, repo
from app.worldmodel import timeline
from app.record.types import (
    AwaitingPatient, AwaitingReview, Committed, Conflict, ConflictId, Document, DocumentHash, DraftFact, Fact, FactId, FactResource,
    Finding, FindingKind, IngestOutcome, PatientId, ProfileVersion, Rejected, Resolution,
)
from app import trace
from app.trace.events import (
    CriticReviewed, IngestRetried, IngestStarted, IntakeDrafted, PatientResolved, ProfileCommitted, RunAwaitingPatient,
    RunAwaitingReview, RunRejected,
)
from app.trace.state import IngestRunState, reduce_ingest


_patient_locks: dict[PatientId, asyncio.Lock] = {}


def patient_lock(patient_id: PatientId) -> asyncio.Lock:
    """One ingest at a time per patient (in this process): each commit numbers its version from the previous
    one, so several Documents added in one go become v2, v3, ... in turn instead of racing for the same number."""
    return _patient_locks.setdefault(patient_id, asyncio.Lock())


# ---- step results (closed set) ---------------------------------------------

@dataclass(frozen=True)
class Retry:
    feedback: tuple[Finding, ...]      # only retryable findings; fed back to Intake

@dataclass(frozen=True)
class Escalate:
    conflicts: tuple[Conflict, ...]
    accepted_drafts: tuple[DraftFact, ...]   # drafts with no findings; kept for commit after confirm

@dataclass(frozen=True)
class Accept:
    drafts: tuple[DraftFact, ...]

@dataclass(frozen=True)
class Exhausted:
    last_findings: tuple[Finding, ...]

Step = Retry | Escalate | Accept | Exhausted

# One drafting attempt: (ctx, doc, feedback, run_id) -> drafts. intake.extract is the default (model, FAST lane);
# a questionnaire's structured answers use structured_drafter (code, no model).
Drafter = Callable[[Ctx, Document, tuple[Finding, ...], trace.RunId], Awaitable[tuple[DraftFact, ...]]]


def structured_drafter(drafts: tuple[DraftFact, ...]) -> Drafter:
    """Drafts already made in code (structured questionnaire answers). Traced like an Intake attempt."""
    async def draft(ctx: Ctx, doc: Document, feedback: tuple[Finding, ...], run_id: trace.RunId):
        await trace.append(ctx.writer, run_id, IntakeDrafted(
            actor="questionnaire", attempt=1 + bool(feedback), drafts=[asdict(d) for d in drafts],
            model_answered="none: structured answers"))
        return drafts
    return draft


def questionnaire_drafter(structured: tuple[DraftFact, ...], free_text: Document,
                          settle: Callable[[DraftFact], DraftFact]) -> Drafter:
    """A questionnaire's attempt: structured answers drafted in code, then free-text answers through the Intake
    agent reading `free_text` (only the free-text answers, with Document page numbers). No free text, no model
    call. On a retry the agent gets only the findings about its own drafts, re-indexed to its list."""
    code = structured_drafter(structured)

    async def draft(ctx: Ctx, doc: Document, feedback: tuple[Finding, ...], run_id: trace.RunId):
        drafts = await code(ctx, doc, feedback, run_id)
        if not free_text.pages:
            return drafts
        n = len(drafts)
        own = tuple(replace(f, draft_index=f.draft_index - n) for f in feedback if f.draft_index >= n)
        return drafts + tuple(settle(d) for d in await intake.extract(ctx, free_text, own, run_id))
    return draft


def region_drafter() -> Drafter:
    """A clinical Document read into Regions: one Intake call per page that has citable Regions, all with the same
    prompt. On a retry only the pages whose drafts had findings are read again, each with the findings about its own
    drafts; the other pages keep their drafts (traced again, so the attempt's drafts are the whole Document's)."""
    by_page: dict[int, tuple[DraftFact, ...]] = {}
    attempt = 0

    async def draft(ctx: Ctx, doc: Document, feedback: tuple[Finding, ...], run_id: trace.RunId):
        nonlocal attempt
        attempt += 1
        order = [p.number for p in doc.pages if doc.intake_regions(p.number)]
        if attempt > 1:
            flat = [(n, i) for n in order for i in range(len(by_page.get(n, ())))]
            own: dict[int, list[Finding]] = {}
            for f in feedback:
                own.setdefault(flat[f.draft_index][0], []).append(f)
        for n in order:
            if attempt == 1 or n in own:
                by_page[n] = await intake.extract_page(ctx, doc, n, tuple(own.get(n, ())) if attempt > 1 else (),
                                                       attempt, run_id)
            else:
                await trace.append(ctx.writer, run_id, IntakeDrafted(
                    actor="intake", attempt=attempt, drafts=[asdict(d) for d in by_page[n]],
                    model_answered=f"none: page {n} kept from attempt {attempt - 1}"))
        return tuple(d for n in order for d in by_page.get(n, ()))
    return draft


def decide(findings: tuple[Finding, ...], drafts: tuple[DraftFact, ...], attempt: int, max_attempts: int,
           current: ProfileVersion | None) -> Step:
    """PURE. The whole loop policy in one function; table-tested.

    # TODO pseudocode
    #   conflicts = [f for f in findings if f.severity == "conflict"]
    #   retryable = [f for f in findings if f.severity == "retryable"]
    #   if conflicts:  -> Escalate(conflicts→Conflict objects, accepted_drafts = drafts without any finding)
    #        (conflicts are never retried: re-reading the Document cannot change what it says)
    #   elif retryable and attempt < max_attempts: -> Retry(retryable)
    #   elif retryable:  -> Exhausted(retryable)      # bound reached
    #   elif not drafts: -> Exhausted(())             # intake found nothing twice
    #   else: -> Accept(drafts)
    """
    # A duplicate of an accepted Fact is dropped, not retried: the record already says it (#9).
    duplicates = {f.draft_index for f in findings if f.kind == FindingKind.DUPLICATE_OF_ACCEPTED}
    findings = tuple(f for f in findings if f.draft_index not in duplicates)
    conflicts = tuple(f for f in findings if f.severity == "conflict")
    retryable = tuple(f for f in findings if f.severity == "retryable")
    if conflicts:
        flagged = {f.draft_index for f in findings}
        accepted = {f.id: f for f in current.facts} if current is not None else {}
        return Escalate(
            conflicts=tuple(Conflict(id=f"conflict:{n}:{f.draft_index}", draft=drafts[f.draft_index],
                                     accepted=accepted.get(f.accepted_fact_id), message=f.message)
                            for n, f in enumerate(conflicts)),
            accepted_drafts=tuple(d for i, d in enumerate(drafts) if i not in flagged | duplicates))
    if retryable:
        return Retry(retryable) if attempt < max_attempts else Exhausted(retryable)
    if not drafts:
        return Exhausted(())
    # Every draft a duplicate (only free text or the Respondent changed): a new version with no new Facts.
    return Accept(tuple(d for i, d in enumerate(drafts) if i not in duplicates))


def drafter_for(doc: Document) -> Drafter:
    """The Intake agent for a clinical Document: page by page over its Regions (region_drafter), or in one call over its
    page text for a Document stored before Documents were read into Regions. For an Intake questionnaire, its answers are read back from the
    Document itself: structured ones drafted in code, free-text ones through the agent (questionnaire_drafter)."""
    if not doc.is_questionnaire:
        return region_drafter() if doc.regions else intake.extract
    answers = questionnaire.answers_from_pages(doc.pages)
    structured = questionnaire.structured_drafts(answers, doc.respondent, doc.pages, doc.uploaded_at)
    free_text = replace(doc, pages=questionnaire.free_text_pages(answers, doc.respondent))
    return questionnaire_drafter(structured, free_text, questionnaire.settle_free_text)


async def run_ingest(ctx: Ctx, doc: Document, run_id: trace.RunId, max_attempts: int) -> IngestOutcome:
    """Drive the loop. One place; reads like the state machine it is.

    # TODO pseudocode
    #   current = await repo.current_version(ctx.agent_reader, doc.patient_id)   # via Zetaris (ADR 0001)
    #   await trace.append(ctx.writer, run_id, IngestStarted(document_hash=doc.hash, pages=len(doc.pages)))
    #   feedback = ()
    #   for attempt in range(1, max_attempts + 1):
    #       drafts = await intake.extract(ctx, doc, feedback, run_id)        # LLM fast lane; emits IntakeDrafted
    #       findings = critic.review(drafts, doc, current)                    # PURE
    #       await trace.append(ctx.writer, run_id, CriticReviewed(attempt, findings))
    #       match decide(findings, drafts, attempt, max_attempts, current):
    #           case Accept(ds):      return await commit(ctx, doc, ds, run_id)
    #           case Escalate(cs, ok): await trace.append(..., RunAwaitingPatient(cs, ok)); return AwaitingPatient(run_id, cs)
    #           case Retry(fb):       await trace.append(..., IngestRetried(attempt, fb)); feedback = fb
    #           case Exhausted(fs):   await trace.append(..., RunRejected(reason)); return Rejected(run_id, reason)
    #   unreachable: decide() returns a terminal step on attempt == max_attempts
    """
    drafter = drafter_for(doc)
    current = await repo.current_version(ctx.agent_reader, doc.patient_id)
    await trace.append(ctx.writer, run_id, IngestStarted(actor="record", document_hash=doc.hash, pages=len(doc.pages)))
    feedback: tuple[Finding, ...] = ()
    for attempt in range(1, max_attempts + 1):
        try:
            drafts = await drafter(ctx, doc, feedback, run_id)
        except LlmUnavailable as e:   # nothing is committed; the Respondent can submit again
            reason = f"the Intake model is unavailable ({e})"
            await trace.append(ctx.writer, run_id, RunRejected(actor="record", reason=reason))
            return Rejected(run_id, reason)
        findings = critic.review(drafts, doc, current)
        await trace.append(ctx.writer, run_id, CriticReviewed(actor="critic", attempt=attempt,
                                                              findings=[asdict(f) for f in findings]))
        match decide(findings, drafts, attempt, max_attempts, current):
            case Accept(drafts=ds):
                return await park_or_commit(ctx, doc, ds, run_id)
            case Escalate(conflicts=cs, accepted_drafts=ok):
                cs = tuple(replace(c, document_hash=doc.hash) for c in cs)
                await trace.append(ctx.writer, run_id, RunAwaitingPatient(
                    actor="critic", conflicts=[asdict(c) for c in cs], accepted_drafts=[asdict(d) for d in ok]))
                return AwaitingPatient(run_id, cs)
            case Retry(feedback=fb):
                await trace.append(ctx.writer, run_id, IngestRetried(actor="critic", attempt=attempt,
                                                                     feedback=[f.message for f in fb]))
                feedback = fb
            case Exhausted(last_findings=fs):
                reason = "; ".join(f.message for f in fs) or "no Facts found in the document"
                await trace.append(ctx.writer, run_id, RunRejected(actor="record", reason=reason))
                return Rejected(run_id, reason)
    raise AssertionError("decide() returns a terminal step on the last attempt")


class NotAwaitingPatient(Exception):
    """confirm() on a run that is not parked on the patient (already committed, rejected, or still drafting)."""


class InvalidResolution(ValueError):
    """A resolution names a Conflict the run is not waiting on, or an unknown choice."""


def _draft_from(d: dict) -> DraftFact:
    return DraftFact(resource=FactResource(d["resource"]), subject=d["subject"], value=d["value"], unit=d["unit"],
                     observed_on=date.fromisoformat(d["observed_on"]) if d["observed_on"] else None, page=d["page"],
                     quote=d["quote"], question=d.get("question"), span_id=d.get("span_id"),
                     flags=tuple(d.get("flags") or ()))


def _fact_from(d: dict) -> Fact:
    return Fact(id=FactId(d["id"]), document_hash=DocumentHash(d["document_hash"]), page=d["page"],
                resource=FactResource(d["resource"]), subject=d["subject"], value=d["value"], unit=d["unit"],
                observed_on=date.fromisoformat(d["observed_on"]), quote=d["quote"], question=d.get("question"),
                span_id=d.get("span_id"), flags=tuple(d.get("flags") or ()))


def conflict_from(d: dict) -> Conflict:
    """A Conflict as the run log keeps it (RunAwaitingPatient), so a parked run survives a restart."""
    return Conflict(id=ConflictId(d["id"]), draft=_draft_from(d["draft"]),
                    accepted=_fact_from(d["accepted"]) if d.get("accepted") else None, message=d["message"],
                    document_hash=d.get("document_hash"))


def parked(state: IngestRunState, run_id: trace.RunId) -> AwaitingPatient | AwaitingReview | None:
    """The AwaitingPatient or AwaitingReview a run's folded state describes, or None if the run is not parked."""
    if state.phase == "awaiting_review":
        return AwaitingReview(run_id, tuple(_draft_from(r["draft"]) for r in state.review))
    if state.phase != "awaiting_patient":
        return None
    return AwaitingPatient(run_id, tuple(conflict_from(c) for c in state.conflicts))


_CHOICES = ("keep_accepted", "accept_draft", "discard_both")


async def resume_after_confirm(ctx: Ctx, doc: Document, run_id: trace.RunId,
                               resolutions: list[Resolution]) -> IngestOutcome:
    """Rehydrate the parked run from its log, record the Respondent's choices, then commit once every Conflict is
    resolved (partial resolutions stay AwaitingPatient with the rest). The next version holds the loop's accepted
    drafts, plus each draft the Respondent accepted; an accepted Fact the Respondent overruled ("accept_draft") or
    discarded ("discard_both") is left out of it. Facts are never deleted: earlier versions keep citing it."""
    state = await trace.project_ingest(ctx.ui_reader, run_id)
    if state.phase != "awaiting_patient":
        raise NotAwaitingPatient(f"run {run_id} is {state.phase}, not awaiting the patient")
    waiting = {c["id"] for c in state.conflicts}
    for r in resolutions:
        if r.conflict_id not in waiting or r.choice not in _CHOICES:
            raise InvalidResolution(f"{r.conflict_id}: not a Conflict this run is waiting on, or not one of {_CHOICES}")
    if resolutions:
        event = PatientResolved(actor="patient", resolutions=[asdict(r) for r in resolutions])
        await trace.append(ctx.writer, run_id, event)
        state = reduce_ingest(state, event)
    if state.conflicts:
        return parked(state, run_id)
    drafts = [_draft_from(d) for d in state.accepted_drafts]
    withdrawn: set[FactId] = set()
    for r in state.resolved:
        conflict = conflict_from(r["conflict"])
        if r["choice"] == "accept_draft":
            drafts.append(conflict.draft)
        if r["choice"] in ("accept_draft", "discard_both") and conflict.accepted is not None:
            withdrawn.add(conflict.accepted.id)
    return await park_or_commit(ctx, doc, tuple(drafts), run_id, withdrawn=frozenset(withdrawn))


def needs_review(doc: Document) -> bool:
    """A letter (a Document read into Regions) waits for Letter review before its Facts are committed (ADR 0006)."""
    return bool(doc.regions) and not doc.is_questionnaire


async def park_or_commit(ctx: Ctx, doc: Document, drafts: tuple[DraftFact, ...], run_id: trace.RunId, *,
                         withdrawn: frozenset[FactId] = frozenset()) -> Committed | AwaitingReview:
    """Accepted drafts: a letter's park for Letter review, uncommitted (with what a resolved Conflict withdrew);
    anything else's commit now."""
    if not needs_review(doc):
        return await commit(ctx, doc, drafts, run_id, withdrawn=withdrawn)
    await trace.append(ctx.writer, run_id, RunAwaitingReview(
        actor="record", drafts=[asdict(d) for d in drafts], withdrawn=sorted(withdrawn)))
    return AwaitingReview(run_id, drafts)


def reviewed_drafts(doc: Document, state: IngestRunState, *, use_all_as_read: bool) -> tuple[DraftFact, ...]:
    """PURE. What a Letter review commits, from the parked run's state: every draft but those marked "Not right",
    each kept one checked; with use_all_as_read, every draft, none checked. A Document date the Respondent corrected
    (doc.document_date) re-dates the drafts it dated (dates.redated)."""
    out = []
    for r in state.review:
        decision = None if use_all_as_read else r["decision"]
        if decision == "drop":
            continue
        d = replace(_draft_from(r["draft"]), checked=decision == "keep")
        if doc.document_date is not None:
            on, flags = dates.redated(d.observed_on, d.flags, d.quote, doc.document_date)
            d = replace(d, observed_on=on, flags=flags)
        out.append(d)
    return tuple(out)


async def commit_review(ctx: Ctx, doc: Document, run_id: trace.RunId, state: IngestRunState, *,
                        use_all_as_read: bool) -> Committed:
    """Commit a parked letter run as reviewed (reviewed_drafts). A dropped draft never reaches the World Model."""
    return await commit(ctx, doc, reviewed_drafts(doc, state, use_all_as_read=use_all_as_read), run_id,
                        withdrawn=frozenset(FactId(i) for i in state.withdrawn))


async def commit(ctx: Ctx, doc: Document, drafts: tuple[DraftFact, ...], run_id: trace.RunId, *,
                 withdrawn: frozenset[FactId] = frozenset()) -> Committed:
    """timeline.commit_profile_version(ctx.wm, ...): assert_fact per draft + snapshot, each appended
    with its projection rows in one transaction (World Model is the only writer, ADR 0001), then
    append ProfileCommitted to the trace.

    Idempotent: fact ids are content-derived and the snapshot is keyed by document hash, so a
    retry after a crash returns the existing version and only the missing trace event is appended.

    A questionnaire resubmission that clears a question answered before (a medicine no longer taken) also withdraws
    that question's Patient-reported Facts from the new version; earlier versions keep them.
    """
    if doc.is_questionnaire:
        withdrawn |= await _cleared(ctx, doc)
    version = await timeline.commit_profile_version(ctx.wm, doc.patient_id, doc, drafts, run_id, withdrawn=withdrawn)
    await trace.append(ctx.writer, run_id, ProfileCommitted(actor="record", profile_version_id=version.id,
                                                            version_number=version.number, facts_added=len(drafts)))
    return Committed(run_id, version)


async def _cleared(ctx: Ctx, doc: Document) -> frozenset[FactId]:
    """The current Patient-reported Facts whose question this questionnaire Document leaves unanswered."""
    current = await repo.current_version(ctx.agent_reader, doc.patient_id)
    blank = questionnaire.skipped(doc.pages)
    return frozenset(f.id for f in (current.facts if current else ()) if f.question in blank)
