"""app/enquiry — ENQUIRY module. Public surface.

Owns: Enquiries — an email body the Respondent edits, copies and sends themselves to a Trial's contact (GLOSSARY).
Hides: which template a Trial gets, the clinical details offered, the recipient choice, the prompt.

Nothing here is stored and nothing is sent: `draft` reads the record, the Trial and its Verdict, makes one fast-lane
model call (not traced to a run, so no llm_call row either) and returns the draft. The model sees only the
de-identified clinical details the Respondent kept ticked; their name and contact stay placeholders for them to fill
in. Templates are keyed by kind: "open" asks about taking part (#28); a Closed trial template (#29) is added in
templates.TEMPLATES.
"""
from __future__ import annotations

from app import llm, matching, record, trials
from app.ctx import Ctx
from app.enquiry import details as clinical, recipient as recipients, templates
from app.enquiry.types import ClinicalDetail, Enquiry, Recipient
from app.record import ProfileVersionId
from app.trials import NctId

__all__ = ["draft", "Enquiry", "ClinicalDetail", "Recipient", "NoVerdict", "NoTemplate", "NAME", "CONTACT"]

NAME, CONTACT = templates.NAME, templates.CONTACT


class NoVerdict(LookupError):
    """An Open trial's Enquiry cites its Verdict; there is none for this Trial at this Profile version."""


class NoTemplate(LookupError):
    """No Enquiry template for this kind of Trial yet (Closed trials: #29)."""


async def draft(ctx: Ctx, nct_id: NctId, version_id: ProfileVersionId, *,
                include: frozenset[str] | None = None) -> Enquiry:
    """The Enquiry for the Trial from this Profile version. `include` is the ids of the clinical details the
    Respondent kept ticked (None: all of them); unticked details are never put in the prompt. Raises
    record.NotFound (unknown version), LookupError (unknown Trial), NoVerdict, NoTemplate and llm.LlmUnavailable."""
    profile = await record.profile_version(ctx, version_id)
    trial = await trials.trial(ctx, nct_id)
    if trial is None:
        raise LookupError(f"no Trial {nct_id}")
    kind = "open" if trial.status in trials.ACTIVE_STATUSES else "closed"
    template = templates.TEMPLATES.get(kind)
    if template is None:
        raise NoTemplate(f"Enquiries for Closed trials are not available yet ({nct_id})")
    verdict = await matching.verdict(ctx, nct_id, version_id)
    if verdict is None:
        raise NoVerdict(f"no Verdict for {nct_id} at {version_id}")

    offered = clinical.offered(profile, ctx.now().date())
    kept = tuple(d for d in offered if include is None or d.id in include)
    contacts = await trials.contacts(ctx, nct_id)
    at = (await record.search_preferences(ctx, profile.patient_id)).location
    to = recipients.for_open(await trials.sites(ctx, nct_id), contacts, at)
    criteria = {c.id: c for c in await trials.criteria(ctx, nct_id)}
    unknown = tuple(criteria[r.criterion_id] for r in verdict.results
                    if r.outcome == matching.Outcome.UNKNOWN and r.criterion_id in criteria)
    written = await llm.complete(ctx, llm.Lane.FAST, system=template.system,
                                 user=template.prompt(trial, verdict.outcome, unknown, kept), out=templates.Written,
                                 run_id=None)
    return Enquiry(nct_id=nct_id, template=kind, subject=template.subject(trial),
                   body=templates.letter(to, written.value.body), recipient=to, sponsor=contacts.sponsor,
                   details=tuple((d, d in kept) for d in offered))
