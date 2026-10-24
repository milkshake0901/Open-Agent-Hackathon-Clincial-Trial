"""app/worldmodel — the Meterless World Model engine (our Python implementation) and the
timeline adapter that maps TrialMatch onto it. Domain modules import `timeline`, never `engine`."""
from app.worldmodel import timeline
from app.worldmodel.engine import IngestObservation, IngestReport, Provenance, WorldModel
from app.worldmodel.resolve import decide
from app.worldmodel.stable_ids import entity_id_from_name, normalize_name
from app.worldmodel.store import InMemoryEventStore, PgEventStore

__all__ = [
    "WorldModel", "Provenance", "IngestObservation", "IngestReport", "timeline",
    "decide", "entity_id_from_name", "normalize_name", "PgEventStore", "InMemoryEventStore",
]
