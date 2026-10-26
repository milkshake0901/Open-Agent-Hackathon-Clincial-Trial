"""app/worldmodel/timeline.py — the ONE place that maps TrialMatch domain operations onto
World Model primitives. record, trials and matching call these; none of them call the engine.

  Patient            entity  type=patient
  Document           context type=document, id=doc:<hash>; Facts carry it as provenance
  Fact               assert_fact(about=patient, predicate=<subject>, value={value, unit, resource, page, quote},
                                 source=Provenance(kind="file", at=<observed_on>, checksum=<doc hash>,
                                                   url="doc:<hash>#page=<n>", run_id=...))
                     observed_on IS the record time, so "current" is plain supersession (ADR 0002)
  Profile version    snapshot(entities=[patient], attrs={kind: "profile", number, document_hash, fact_ids})
  Trial              ingest([IngestObservation(type="trial", external_id=<NCT>, text=<eligibility text>,
                                               attrs={..., eligibility_hash, criteria})]) → entity trial:<NCT>;
                     changed_ids drive the Re-scan. The Australia-wide ingest leaves criteria empty (ADR 0004):
  Criteria           ingest([IngestObservation(type="criteria", external_id=<NCT>:<eligibility hash>,
                                               attrs={nct_id, eligibility_hash, criteria})]), written the first
                     time a Trial's Criteria are asked for; immutable per hash, so a re-split appends nothing
  Outcome summary    ingest([IngestObservation(type="outcome_summary", external_id=<NCT>:<Outcome content hash>,
                                               text=<summary>, attrs={nct_id, outcomes_hash, model})]), written the
                     first time a Closed trial's Outcomes are opened (#26)
  Verdict            relate(patient → trial:<NCT>, type="verdict", context="verdict:<NCT>",
                            valid_from=<profile version time>,
                            attrs={outcome, profile_version_id, eligibility_hash, results, questions, degraded, ...})
                     The context keys the edge per Trial, so a Verdict on one Trial never closes another Trial's;
                     a later Verdict on the SAME Trial (new version or hash) closes the old edge, so
                     edges_from(patient, via="verdict", at=t) answers "what did we believe at v3"
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.matching import Verdict
    from app.record import Document, DraftFact, PatientId, ProfileVersion
    from app.trace import RunId
    from app.trials import Contact, Criterion, Outcomes, OutcomeSummary, TrialContacts, TrialSite, Trial
    from app.worldmodel.engine import IngestReport, WorldModel


def patient_entity_id(patient_id: str) -> str:
    return f"patient:record:{patient_id}"


async def commit_profile_version(wm: "WorldModel", patient_id: "PatientId", doc: "Document",
                                 drafts: tuple["DraftFact", ...], run_id: "RunId", *,
                                 withdrawn: frozenset[str] = frozenset()) -> "ProfileVersion":
    """assert_fact per draft, then snapshot. Idempotent: an existing snapshot for this document hash is returned.
    The new version's Fact set is the previous version's set, less `withdrawn` (accepted Facts the patient overruled
    in a Conflict; they stay in earlier versions), plus this Document's Facts (ADR 0002)."""
    from app.record import ProfileVersion
    from app.worldmodel.engine import Provenance

    def as_version(snap) -> "ProfileVersion":
        a = snap.attrs
        return ProfileVersion(id=snap.id, patient_id=a["patient_id"], number=a["number"],
                              document_hash=a["document_hash"], fact_ids=frozenset(a["fact_ids"]))

    profiles = [s for s in wm.snapshots() if s.attrs.get("kind") == "profile" and s.attrs.get("patient_id") == patient_id]
    existing = next((s for s in profiles if s.attrs["document_hash"] == doc.hash), None)
    if existing is not None:
        return as_version(existing)

    doc_source = Provenance(kind="file", at=doc.uploaded_at.isoformat(), by="record", url=f"doc:{doc.hash}",
                            checksum=doc.hash, run_id=run_id)
    about = patient_entity_id(patient_id)
    await wm.upsert_entity(type="patient", external_key=("record", patient_id), source=doc_source)
    await wm.upsert_context(type="document", id=f"doc:{doc.hash}", source=doc_source,
                            attrs={"filename": doc.filename, "respondent": doc.respondent})
    new_ids = []
    for d in drafts:
        source = Provenance(kind="file", at=d.observed_on.isoformat(), by="record",
                            url=f"doc:{doc.hash}#page={d.page}", checksum=doc.hash, run_id=run_id)
        value = {"value": d.value, "unit": d.unit, "resource": str(d.resource), "page": d.page, "quote": d.quote,
                 "question": d.question}
        if d.span_id is not None:   # only when set: a Fact's id is derived from its value, so others keep theirs
            value["span_id"] = d.span_id
        if d.flags:                 # likewise
            value["flags"] = list(d.flags)
        fact = await wm.assert_fact(about=about, predicate=d.subject, source=source, context=f"doc:{doc.hash}",
                                    value=value)
        new_ids.append(fact.id)
    previous = set(profiles[-1].attrs["fact_ids"]) if profiles else set()
    snap = await wm.snapshot(entities=[about], source=doc_source, attrs={
        "kind": "profile", "patient_id": patient_id, "number": len(profiles) + 1, "document_hash": doc.hash,
        "fact_ids": sorted((previous - withdrawn) | set(new_ids))})
    return as_version(snap)


def trial_entity_id(nct_id: str) -> str:
    return f"trial:{nct_id}"


@dataclass(frozen=True)
class LoadedTrial:
    """One Trial as an ingest loaded it, for record_trials. Sites (with their contacts), contacts and Outcomes left
    None keep the stored ones; given, they replace them."""
    trial: "Trial"
    criteria: "tuple[Criterion, ...]" = ()
    sites: "tuple[TrialSite, ...] | None" = None
    contacts: "TrialContacts | None" = None
    outcomes: "Outcomes | None" = None


async def record_trials(wm: "WorldModel", loaded: "list[LoadedTrial]", run_id: "RunId | None") -> "IngestReport":
    """One ingest of the loaded Trials keyed by NCT id. Unchanged content appends nothing (the fetch time is the
    observation time, not content), so changed_ids are the new or edited Trials."""
    from app.trials import page_url
    from app.worldmodel.engine import IngestObservation, Provenance

    observations = []
    for one in loaded:
        t, criteria, sites, contacts, outcomes = one.trial, one.criteria, one.sites, one.contacts, one.outcomes
        source = Provenance(kind="api", at=t.fetched_at, by="trials", url=page_url(t.nct_id), run_id=run_id)
        observations.append(IngestObservation(
            type="trial", external_id=t.nct_id, title=t.title, at=t.fetched_at, source=source,
            text=t.eligibility_text, attrs={
                "conditions": list(t.conditions), "status": t.status, "eligibility_hash": t.eligibility_hash,
                "source": t.source, "primary_completion_date": t.primary_completion_date,
                "completion_date": t.completion_date, "last_update_date": t.last_update_date,
                "criteria": [{"id": c.id, "kind": str(c.kind), "ordinal": c.ordinal, "text": c.text}
                             for c in criteria],
                **({"sites": [{"facility": s.facility, "city": s.city, "country": s.country, "status": s.status,
                               "lat": s.lat, "lon": s.lon, "contacts": [_contact(c) for c in s.contacts]}
                              for s in sites]} if sites is not None else {}),
                **({"contacts": {
                    "sponsor": contacts.sponsor,
                    "responsible_party": _contact(contacts.responsible_party) if contacts.responsible_party else None,
                    "central": [_contact(c) for c in contacts.central],
                    "officials": [_contact(c) for c in contacts.officials]}} if contacts is not None else {}),
                **({"outcomes": _outcomes(outcomes)} if outcomes is not None else {})}))
    return await wm.ingest(observations, run_id=run_id)


def _outcomes(o: "Outcomes") -> dict:
    measures = lambda ms: [{"measure": m.measure, "description": m.description, "time_frame": m.time_frame}  # noqa: E731
                           for m in ms]
    return {"primary": measures(o.primary), "secondary": measures(o.secondary), "other": measures(o.other),
            "has_results": o.has_results,
            "results": [{"type": r.type, "title": r.title, "description": r.description, "time_frame": r.time_frame,
                         "unit": r.unit, "param_type": r.param_type,
                         "values": [{"group": v.group, "value": v.value, "spread": v.spread, "lower": v.lower,
                                     "upper": v.upper, "label": v.label} for v in r.values]} for r in o.results],
            "publications": [{"pmid": p.pmid, "type": p.type, "citation": p.citation} for p in o.publications]}


def _contact(c: "Contact") -> dict:
    return {"name": c.name, "role": c.role, "email": c.email, "phone": c.phone, "affiliation": c.affiliation,
            "title": c.title}
async def drop_trials(wm: "WorldModel", trials: "list[Trial]", at: str) -> None:
    """Stored Trials an ingest no longer keeps (ADR 0004: a Closed trial past the 15-year cutoff, or a Trial now
    withdrawn, in a status neither Open nor Closed, or with no Australian site): each Trial entity is replaced by a
    dropped marker, so the projection no longer lists or judges it; its Criteria and any Verdicts stay as history (ADR 0002).
    Idempotent: dropping a dropped Trial appends nothing, and a later ingest of the study records it again."""
    from app.trials import page_url
    from app.worldmodel.engine import IngestObservation, Provenance

    await wm.ingest([IngestObservation(
        type="trial", external_id=t.nct_id, title=t.title, at=at, attrs={"dropped": True},
        source=Provenance(kind="api", at=at, by="trials", url=page_url(t.nct_id)))
        for t in trials])


async def record_criteria(wm: "WorldModel", trial: "Trial", criteria: "tuple[Criterion, ...]") -> None:
    """The Criteria split from the Trial's current eligibility text, recorded apart from the Trial so that splitting
    lazily never changes the Trial's content (a later identical ingest stays unchanged). Idempotent per hash."""
    from app.trials import page_url
    from app.worldmodel.engine import IngestObservation, Provenance

    key = f"{trial.nct_id}:{trial.eligibility_hash}"
    source = Provenance(kind="api", at=trial.fetched_at, by="trials", url=page_url(trial.nct_id))
    await wm.ingest([IngestObservation(
        type="criteria", external_id=key, title=trial.title, at=trial.fetched_at, source=source,
        text=trial.eligibility_text, attrs={
            "nct_id": trial.nct_id, "eligibility_hash": trial.eligibility_hash,
            "criteria": [{"id": c.id, "kind": str(c.kind), "ordinal": c.ordinal, "text": c.text} for c in criteria]})])


async def record_outcome_summary(wm: "WorldModel", trial: "Trial", summary: "OutcomeSummary", model: str,
                                 at: str) -> None:
    """The plain-language summary written for the Trial's Outcomes, recorded apart from the Trial so that it never
    changes the Trial's content. Keyed by (NCT id, Outcome content hash): changed Outcomes get a new summary and
    the old one stays as history."""
    from app.trials import page_url
    from app.worldmodel.engine import IngestObservation, Provenance

    await wm.ingest([IngestObservation(
        type="outcome_summary", external_id=f"{trial.nct_id}:{summary.outcomes_hash}", title=trial.title, at=at,
        text=summary.text, attrs={"nct_id": trial.nct_id, "outcomes_hash": summary.outcomes_hash, "model": model},
        source=Provenance(kind="agent", at=at, by="trials", url=page_url(trial.nct_id)))])


async def record_verdict(wm: "WorldModel", patient_id: "PatientId", verdict: "Verdict") -> None:
    """relate(patient → trial, type="verdict", context per Trial). Keyed by (Trial, eligibility hash, Profile
    version), ADR 0002: the attrs carry both, so a new version or hash opens a new edge and closes the old one."""
    from app.worldmodel.engine import Provenance

    snap = next(s for s in wm.snapshots() if s.id == verdict.profile_version_id)
    source = Provenance(kind="agent", at=snap.at, by="matching", run_id=verdict.run_id)
    await wm.relate(
        from_id=patient_entity_id(patient_id), type="verdict", to_id=trial_entity_id(verdict.nct_id),
        context=f"verdict:{verdict.nct_id}", valid_from=snap.at, source=source, attrs={
            "nct_id": verdict.nct_id, "profile_version_id": verdict.profile_version_id,
            "eligibility_hash": verdict.eligibility_hash, "outcome": str(verdict.outcome), "run_id": verdict.run_id,
            "attempts": verdict.attempts, "unsupported_downgraded": verdict.unsupported_downgraded,
            "degraded": verdict.degraded,
            "results": [{"criterion_id": r.criterion_id, "outcome": str(r.outcome),
                         "fact_id": r.citation.fact_id if r.citation else None, "rationale": r.rationale,
                         "ask": r.ask} for r in verdict.results],
            "questions": [{"criterion_id": q.criterion_id, "subject": q.subject, "text": q.text}
                          for q in verdict.questions],
            "respondent_questions": [{"criterion_id": q.criterion_id, "question_id": q.question_id,
                                      "question": q.question, "subject": q.subject, "text": q.text}
                                     for q in verdict.respondent_questions]})
