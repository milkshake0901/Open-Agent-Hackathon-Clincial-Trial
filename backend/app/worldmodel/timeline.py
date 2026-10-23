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


async def commit_profile_version(wm: "WorldModel", patient_id: "PatientId", doc: "Document",
                                 drafts: tuple["DraftFact", ...], run_id: "RunId") -> "ProfileVersion":
    """assert_fact per draft, then snapshot. Idempotent: an existing snapshot for this document hash is returned."""
    raise NotImplementedError


async def record_trials(wm: "WorldModel", trials: list["Trial"], run_id: "RunId | None") -> "IngestReport":
    raise NotImplementedError


async def record_verdict(wm: "WorldModel", patient_id: "PatientId", verdict: "Verdict") -> None:
    """relate(patient → trial, type="verdict"). Keyed by (Trial, eligibility hash, Profile version), ADR 0002."""
    raise NotImplementedError
