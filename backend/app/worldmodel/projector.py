"""app/worldmodel/projector.py — World Model events → the relational tables Zetaris reads.

Called by PgEventStore inside the append transaction. Pure mapping from one event to row
writes; it never reads the World Model and never calls a model. `scripts/rebuild_projections.py`
truncates the projected tables and replays wm_event through this, which proves they are derived.

Mapping (see timeline.py for how domain operations become these events):
  assertFact  about=patient:*         → fact                     (append-only)
  snapshot    attrs.kind=profile      → profile_version + profile_version_fact
  upsertEntity type=trial             → trial (upsert) + criterion rows from attrs.criteria (immutable per hash)
                                        + trial_site rows from attrs.sites (replaced)
                                        + trial_contact rows from attrs.contacts and each site's contacts (replaced)
  upsertEntity type=criteria          → criterion rows split lazily for one (Trial, eligibility hash)
  relate      type=verdict, open edge → verdict + criterion_result + doctor_question + respondent_question
              (the closing re-emit of a superseded edge changes no row: old Verdicts are history, ADR 0002)
"""
from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.sql.writer import Tx
    from app.worldmodel.engine import WorldEvent


async def project(tx: "Tx", event: "WorldEvent") -> None:
    """Unknown combinations are ignored on purpose (the engine stores more than the app projects)."""
    from app.worldmodel.engine import Entity, Fact, Relationship, Snapshot

    p = event.payload
    if event.kind == "assertFact" and isinstance(p, Fact) and p.about.startswith("patient:"):
        await _fact(tx, p)
    elif event.kind == "snapshot" and isinstance(p, Snapshot) and p.attrs.get("kind") == "profile":
        await _profile_version(tx, p)
    elif event.kind == "upsertEntity" and isinstance(p, Entity) and p.type == "trial":
        await _trial(tx, p)
    elif event.kind == "upsertEntity" and isinstance(p, Entity) and p.type == "criteria":
        await _criteria(tx, p.attrs["nct_id"], p.attrs["eligibility_hash"], p.attrs["criteria"])
    elif event.kind == "relate" and isinstance(p, Relationship) and p.type == "verdict" and p.valid_to is None:
        await _verdict(tx, p)


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


async def _trial(tx: "Tx", e) -> None:
    a = e.attrs
    await tx.execute(
        "INSERT INTO trial (nct_id, title, conditions, status, eligibility_text, eligibility_hash, source, fetched_at) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7, $8) ON CONFLICT (nct_id) DO UPDATE SET title = EXCLUDED.title, "
        "conditions = EXCLUDED.conditions, status = EXCLUDED.status, eligibility_text = EXCLUDED.eligibility_text, "
        "eligibility_hash = EXCLUDED.eligibility_hash, source = EXCLUDED.source, fetched_at = EXCLUDED.fetched_at",
        (a["external_id"], a["title"], list(a["conditions"]), a["status"], a["text"], a["eligibility_hash"],
         a["source"], _timestamp(a["observed_at"])))
    await _criteria(tx, a["external_id"], a["eligibility_hash"], a["criteria"])
    if "sites" in a:
        await tx.execute("DELETE FROM trial_site WHERE nct_id = $1", (a["external_id"],))
        for i, site in enumerate(a["sites"], 1):
            await tx.execute(
                "INSERT INTO trial_site (nct_id, ordinal, facility, city, country, status, lat, lon) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
                (a["external_id"], i, site["facility"], site["city"], site["country"], site["status"],
                 site["lat"], site["lon"]))
        await tx.execute("DELETE FROM trial_contact WHERE nct_id = $1 AND kind = 'site'", (a["external_id"],))
        for i, site in enumerate(a["sites"], 1):
            await _contacts(tx, a["external_id"], "site", site.get("contacts", ()), site_ordinal=i)
    if "contacts" in a:
        c = a["contacts"]
        await tx.execute("DELETE FROM trial_contact WHERE nct_id = $1 AND kind <> 'site'", (a["external_id"],))
        await _contacts(tx, a["external_id"], "sponsor", [{"name": c["sponsor"]}] if c["sponsor"] else [])
        await _contacts(tx, a["external_id"], "responsible_party",
                        [c["responsible_party"]] if c["responsible_party"] else [])
        await _contacts(tx, a["external_id"], "central", c["central"])
        await _contacts(tx, a["external_id"], "official", c["officials"])


async def _contacts(tx: "Tx", nct_id: str, kind: str, contacts, *, site_ordinal: int = 0) -> None:
    for i, c in enumerate(contacts, 1):
        await tx.execute(
            "INSERT INTO trial_contact (nct_id, kind, site_ordinal, ordinal, name, role, email, phone, affiliation, "
            "title) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)",
            (nct_id, kind, site_ordinal, i, c["name"], c.get("role", ""), c.get("email", ""), c.get("phone", ""),
             c.get("affiliation", ""), c.get("title", "")))


async def _criteria(tx: "Tx", nct_id: str, eligibility_hash: str, criteria: list[dict]) -> None:
    for c in criteria:
        await tx.execute(
            "INSERT INTO criterion (id, nct_id, eligibility_hash, kind, ordinal, text) VALUES ($1, $2, $3, $4, $5, $6) "
            "ON CONFLICT (id) DO NOTHING",
            (c["id"], nct_id, eligibility_hash, c["kind"], c["ordinal"], c["text"]))


async def _verdict(tx: "Tx", r) -> None:
    a = r.attrs
    key = (a["nct_id"], a["eligibility_hash"], a["profile_version_id"])
    inserted = await tx.fetch(
        "INSERT INTO verdict (nct_id, eligibility_hash, profile_version_id, outcome, run_id, attempts, "
        "unsupported_downgraded, degraded) VALUES ($1, $2, $3, $4, $5, $6, $7, $8) ON CONFLICT DO NOTHING "
        "RETURNING nct_id", (*key, a["outcome"], a["run_id"], a["attempts"], a["unsupported_downgraded"], a["degraded"]))
    if not inserted:
        return
    for res in a["results"]:
        await tx.execute(
            "INSERT INTO criterion_result (nct_id, eligibility_hash, profile_version_id, criterion_id, outcome, "
            "fact_id, rationale, ask) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
            (*key, res["criterion_id"], res["outcome"], res["fact_id"], res["rationale"], res.get("ask")))
    for q in a["questions"]:
        await tx.execute(
            "INSERT INTO doctor_question (nct_id, eligibility_hash, profile_version_id, criterion_id, subject, text) "
            "VALUES ($1, $2, $3, $4, $5, $6)", (*key, q["criterion_id"], q["subject"], q["text"]))
    for q in a.get("respondent_questions", ()):
        await tx.execute(
            "INSERT INTO respondent_question (nct_id, eligibility_hash, profile_version_id, criterion_id, question_id, "
            "question, subject, text) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
            (*key, q["criterion_id"], q["question_id"], q["question"], q["subject"], q["text"]))


def _timestamp(iso: str):
    from datetime import UTC, datetime

    t = datetime.fromisoformat(iso)
    return t if t.tzinfo else t.replace(tzinfo=UTC)
