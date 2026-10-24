"""app/worldmodel/timeline.py — the ONE place that maps TrialMatch domain operations onto
World Model primitives. record, trials and matching call these; none of them call the engine.

  Patient            entity  type=patient
  Document           context type=document, id=doc:<hash>; Facts carry it as provenance
  Fact               assert_fact(about=patient, predicate=<subject>, value={value, unit, resource, page, quote},
                                 source=Provenance(kind="file", at=<observed_on>, checksum=<doc hash>,
                                                   url="doc:<hash>#page=<n>", run_id=...))
                     observed_on IS the record time, so "current" is plain supersession (ADR 0002)
  Profile version    snapshot(entities=[patient], attrs={kind: "profile", number, document_hash, fact_ids})
  Trial              ingest([IngestObservation(external_id=<NCT>, ...)]) → changed_ids drive the Re-scan
  Verdict            relate(patient → trial, type="verdict", valid_from=<profile version time>,
                            attrs={outcome, profile_version, eligibility_hash, results, questions, degraded})
                     the old edge closes, so verdict_at(patient, trial, t) answers "what did we believe at v3"
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.matching import Verdict
    from app.record import Document, DraftFact, PatientId, ProfileVersion
    from app.trace import RunId
    from app.trials import Trial
    from app.worldmodel.engine import IngestReport, WorldModel


def patient_entity_id(patient_id: str) -> str:
    return f"patient:record:{patient_id}"


async def commit_profile_version(wm: "WorldModel", patient_id: "PatientId", doc: "Document",
                                 drafts: tuple["DraftFact", ...], run_id: "RunId") -> "ProfileVersion":
    """assert_fact per draft, then snapshot. Idempotent: an existing snapshot for this document hash is returned.
    The new version's Fact set is the previous version's set plus this Document's Facts (ADR 0002)."""
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
        fact = await wm.assert_fact(about=about, predicate=d.subject, source=source, context=f"doc:{doc.hash}",
                                    value={"value": d.value, "unit": d.unit, "resource": str(d.resource),
                                           "page": d.page, "quote": d.quote, "question": d.question})
        new_ids.append(fact.id)
    previous = set(profiles[-1].attrs["fact_ids"]) if profiles else set()
    snap = await wm.snapshot(entities=[about], source=doc_source, attrs={
        "kind": "profile", "patient_id": patient_id, "number": len(profiles) + 1, "document_hash": doc.hash,
        "fact_ids": sorted(previous | set(new_ids))})
    return as_version(snap)


async def record_trials(wm: "WorldModel", trials: list["Trial"], run_id: "RunId | None") -> "IngestReport":
    raise NotImplementedError


async def record_verdict(wm: "WorldModel", patient_id: "PatientId", verdict: "Verdict") -> None:
    """relate(patient → trial, type="verdict"). Keyed by (Trial, eligibility hash, Profile version), ADR 0002."""
    raise NotImplementedError
