"""app/worldmodel/projector.py — World Model events → the relational tables Zetaris reads.

Called by PgEventStore inside the append transaction. Pure mapping from one event to row
writes; it never reads the World Model and never calls a model. `scripts/rebuild_projections.py`
truncates the projected tables and replays wm_event through this, which proves they are derived.

Mapping (see timeline.py for how domain operations become these events):
  assertFact  about=patient:*         → fact                     (append-only)
  snapshot    attrs.kind=profile      → profile_version + profile_version_fact
  upsertEntity type=trial             → trial  (+ criterion rows from attrs.criteria)        [ticket #12]
  relate      type=verdict            → verdict + criterion_result + doctor_question        [ticket #12]
"""
from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.sql.writer import Tx
    from app.worldmodel.engine import WorldEvent


async def project(tx: "Tx", event: "WorldEvent") -> None:
    """Unknown combinations are ignored on purpose (the engine stores more than the app projects)."""
    from app.worldmodel.engine import Fact, Snapshot

    p = event.payload
    if event.kind == "assertFact" and isinstance(p, Fact) and p.about.startswith("patient:"):
        await _fact(tx, p)
    elif event.kind == "snapshot" and isinstance(p, Snapshot) and p.attrs.get("kind") == "profile":
        await _profile_version(tx, p)


async def _fact(tx: "Tx", f) -> None:
    # A supersession re-emits the old Fact with superseded_by set: the row already exists and stays as it was.
    v = f.value
    await tx.execute(
        "INSERT INTO fact (id, document_hash, page, resource, subject, value, unit, observed_on, quote, question) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10) ON CONFLICT (id) DO NOTHING",
        (f.id, f.source.checksum, v["page"], v["resource"], f.predicate, v["value"], v.get("unit"),
         date.fromisoformat(f.source.at[:10]), v["quote"], v.get("question")))


async def _profile_version(tx: "Tx", s) -> None:
    a = s.attrs
    await tx.execute(
        "INSERT INTO profile_version (id, patient_id, number, document_hash) VALUES ($1, $2, $3, $4) "
        "ON CONFLICT (id) DO NOTHING",
        (s.id, a["patient_id"], a["number"], a["document_hash"]))
    for fact_id in a["fact_ids"]:
        await tx.execute(
            "INSERT INTO profile_version_fact (profile_version_id, fact_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
            (s.id, fact_id))
