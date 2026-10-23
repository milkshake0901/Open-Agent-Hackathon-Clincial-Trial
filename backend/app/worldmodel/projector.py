"""app/worldmodel/projector.py — World Model events → the relational tables Zetaris reads.

Called by PgEventStore inside the append transaction. Pure mapping from one event to row
writes; it never reads the World Model and never calls a model. `scripts/rebuild_projections.py`
truncates the projected tables and replays wm_event through this, which proves they are derived.

Mapping (see timeline.py for how domain operations become these events):
  assertFact  about=patient:*         → fact                     (append-only)
  snapshot    attrs.kind=profile      → profile_version + profile_version_fact
  upsertEntity type=trial             → trial  (+ criterion rows from attrs.criteria)
  relate      type=verdict            → verdict + criterion_result + doctor_question
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.sql.writer import Tx
    from app.worldmodel.engine import WorldEvent


async def project(tx: "Tx", event: "WorldEvent") -> None:
    """# TODO: match event.kind and payload type; unknown combinations are ignored on purpose
    (the engine stores more than the app projects), but every mapping above must be covered by a test."""
    raise NotImplementedError
