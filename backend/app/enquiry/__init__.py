"""app/enquiry — ENQUIRY module. Public surface.

Owns: Enquiries — an email body the Respondent edits, copies and sends themselves to a Trial's contact (GLOSSARY).
Hides: which template a Trial gets, the clinical details offered, the recipient choice, the prompt.

Nothing here is stored and nothing is sent. `details` lists the de-identified clinical details an Enquiry may carry,
with no model call, so the Respondent sees and confirms them first; `draft` then reads the record and the Trial
through the agent reader (Zetaris, ADR 0001: an Open trial's Verdict if it has one, a Closed trial's Outcomes), makes
one fast-lane model call (not traced to a run, so no llm_call row either) with only the confirmed details, and
returns the draft. The Respondent's name and contact stay placeholders for them to fill in. An Open trial gets the
OPEN template, asking about taking part (#28); any other, including one that closed after it was judged, the CLOSED
one, about its Outcomes or a follow-on study (#29).
"""
from __future__ import annotations

import logging

from app import llm, logfile, matching, record, trials
from app.ctx import Ctx
# The `details` function below wins the name over the submodule, imported here as `clinical`.
from app.enquiry import details as clinical, recipient as recipients, templates
from app.enquiry.types import ClinicalDetail, Enquiry, EnquiryKind, Recipient
from app.record import ProfileVersionId
from app.trials import NctId

__all__ = ["details", "draft", "Enquiry", "EnquiryKind", "ClinicalDetail", "Recipient", "NAME", "CONTACT"]

NAME, CONTACT = templates.NAME, templates.CONTACT
log = logging.getLogger(__name__)


async def details(ctx: Ctx, nct_id: NctId, version_id: ProfileVersionId) -> tuple[ClinicalDetail, ...]:
    """The clinical details an Enquiry about the Trial from this Profile version may include, for the Respondent to
    confirm before anything is drafted. No model call. Raises record.NotFound (unknown version) and LookupError
    (unknown Trial)."""
    profile = await record.profile_version(ctx, version_id)
    if await trials.trial(ctx, nct_id) is None:
        raise LookupError(f"no Trial {nct_id}")
    return clinical.offered(profile, ctx.now().date())


async def draft(ctx: Ctx, nct_id: NctId, version_id: ProfileVersionId, *, include: frozenset[str]) -> Enquiry:
    """The Enquiry for the Trial from this Profile version. `include` is the ids of the clinical details the
    Respondent confirmed (see `details`); no other detail is put in the prompt. An Open trial with no Verdict yet at
    this version gets the OPEN template citing none. Raises record.NotFound (unknown version), LookupError (unknown
    Trial) and llm.LlmUnavailable."""
    profile = await record.profile_version(ctx, version_id, for_agent=True)
    trial = await trials.trial(ctx, nct_id, for_agent=True)
    if trial is None:
        raise LookupError(f"no Trial {nct_id}")
    offered = clinical.offered(profile, ctx.now().date())
    kept = tuple(d for d in offered if d.id in include)
    contacts = await trials.contacts(ctx, nct_id)
    if trial.is_open:
        template = templates.OPEN
        at = (await record.search_preferences(ctx, profile.patient_id)).location
        to = recipients.for_open(await trials.sites(ctx, nct_id), contacts, at)
        verdict = await matching.verdict(ctx, nct_id, version_id, for_agent=True)
        unknown: tuple[trials.Criterion, ...] = ()
        if verdict is not None:
            criteria = {c.id: c for c in await trials.criteria(ctx, nct_id, for_agent=True)}
            unknown = tuple(criteria[r.criterion_id] for r in verdict.results
                            if r.outcome == matching.Outcome.UNKNOWN and r.criterion_id in criteria)
        user = templates.open_prompt(trial, verdict.outcome if verdict else None, unknown, kept)
    else:   # a Closed trial is never judged, and one judged before it closed is not asked about taking part
        template = templates.CLOSED
        to = recipients.for_closed(await trials.sites(ctx, nct_id), contacts)
        user = templates.closed_prompt(trial, await trials.outcomes(ctx, nct_id, for_agent=True), kept)
    written = await llm.complete(ctx, llm.Lane.FAST, system=template.system, user=user, out=templates.Written,
                                 run_id=None)
    logfile.step(log, "enquiry.drafted", nct_id=nct_id, profile_version_id=version_id, template=template.kind,
                 included=sorted(d.id for d in kept), model_answered=written.model_answered)   # never the recipient or the body
    return Enquiry(nct_id=nct_id, template=template.kind, subject=template.subject(trial),
                   body=templates.letter(to, contacts.sponsor, written.value.body), recipient=to,
                   sponsor=contacts.sponsor, details=tuple((d, d in kept) for d in offered))
