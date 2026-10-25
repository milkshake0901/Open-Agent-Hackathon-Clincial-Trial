"""app/enquiry — ENQUIRY module. Public surface.

Owns: Enquiries — an email body the Respondent edits, copies and sends themselves to a Trial's contact (GLOSSARY).
Hides: which template a Trial gets, the clinical details offered, the recipient choice, the prompt.

Nothing here is stored and nothing is sent: `draft` reads the record and the Trial (an Open trial's Verdict, a Closed
trial's Outcomes), makes one fast-lane model call (not traced to a run, so no llm_call row either) and returns the
draft. The model sees only the de-identified clinical details the Respondent kept ticked; their name and contact stay
placeholders for them to fill in. Templates are keyed by kind: "open" asks about taking part (#28), "closed" about a
Closed trial's Outcomes or a follow-on study (#29). A Trial that closed after it was judged gets the "closed" one.
"""
from __future__ import annotations

from app import llm, matching, record, trials
from app.ctx import Ctx
from app.enquiry import details as clinical, recipient as recipients, templates
from app.enquiry.types import ClinicalDetail, Enquiry, Recipient
from app.record import ProfileVersionId
from app.trials import NctId

__all__ = ["draft", "Enquiry", "ClinicalDetail", "Recipient", "NoVerdict", "NAME", "CONTACT"]

NAME, CONTACT = templates.NAME, templates.CONTACT


class NoVerdict(LookupError):
    """An Open trial's Enquiry cites its Verdict; there is none for this Trial at this Profile version."""


async def draft(ctx: Ctx, nct_id: NctId, version_id: ProfileVersionId, *,
                include: frozenset[str] | None = None) -> Enquiry:
    """The Enquiry for the Trial from this Profile version. `include` is the ids of the clinical details the
    Respondent kept ticked (None: all of them); unticked details are never put in the prompt. Raises
    record.NotFound (unknown version), LookupError (unknown Trial), NoVerdict (an Open trial only) and
    llm.LlmUnavailable."""
    profile = await record.profile_version(ctx, version_id)
    trial = await trials.trial(ctx, nct_id)
    if trial is None:
        raise LookupError(f"no Trial {nct_id}")
    offered = clinical.offered(profile, ctx.now().date())
    kept = tuple(d for d in offered if include is None or d.id in include)
    contacts = await trials.contacts(ctx, nct_id)
    if trial.is_open:
        kind = "open"
        verdict = await matching.verdict(ctx, nct_id, version_id)
        if verdict is None:
            raise NoVerdict(f"no Verdict for {nct_id} at {version_id}")
        at = (await record.search_preferences(ctx, profile.patient_id)).location
        to = recipients.for_open(await trials.sites(ctx, nct_id), contacts, at)
        criteria = {c.id: c for c in await trials.criteria(ctx, nct_id)}
        unknown = tuple(criteria[r.criterion_id] for r in verdict.results
                        if r.outcome == matching.Outcome.UNKNOWN and r.criterion_id in criteria)
        user = templates.TEMPLATES[kind].prompt(trial, verdict.outcome, unknown, kept)
    else:   # a Closed trial is never judged, and one judged before it closed is not asked about taking part
        kind = "closed"
        to = recipients.for_closed(await trials.sites(ctx, nct_id), contacts)
        user = templates.TEMPLATES[kind].prompt(trial, await trials.outcomes(ctx, nct_id), kept)
    template = templates.TEMPLATES[kind]
    written = await llm.complete(ctx, llm.Lane.FAST, system=template.system, user=user, out=templates.Written,
                                 run_id=None)
    return Enquiry(nct_id=nct_id, template=kind, subject=template.subject(trial),
                   body=templates.letter(to, written.value.body), recipient=to, sponsor=contacts.sponsor,
                   details=tuple((d, d in kept) for d in offered))
