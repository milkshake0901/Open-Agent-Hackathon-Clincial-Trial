"""Meterless World Model conformance checks, ported from
Meterless/Meterless engines/world-model/conformance/runner.ts (8 checks, same vectors).

The upstream runner loads a TypeScript module, so it cannot run our Python engine directly.
These tests assert the same invariants with the same inputs; the README reports the result.
"""
from __future__ import annotations

import pytest

from app.worldmodel import IngestObservation, Provenance, WorldModel, decide, entity_id_from_name, normalize_name
from app.worldmodel.engine import MissingProvenance
from app.worldmodel.store import InMemoryEventStore

OBSERVATIONS = [
    IngestObservation(external_id="a1", title="Fed holds rates", at="2026-05-17T14:00:00.000Z",
                      source=Provenance(kind="rss", at="2026-05-17T14:00:00.000Z")),
    IngestObservation(external_id="a2", title="Powell signals patience", at="2026-05-17T16:30:00.000Z",
                      source=Provenance(kind="rss", at="2026-05-17T16:30:00.000Z")),
]


def world() -> WorldModel:
    return WorldModel(namespace="conf", store=InMemoryEventStore())


def test_sid_001_diacritics_and_nbsp_normalize_identically():
    assert normalize_name("José  García") == normalize_name("Jose Garcia")
    assert entity_id_from_name("person", "José García") == entity_id_from_name("person", "jose garcia")


def test_sid_002_distinct_names_stay_distinct():
    assert entity_id_from_name("org", "Acme Corp") != entity_id_from_name("org", "Acme Corporation")
    assert entity_id_from_name("person", "x") != entity_id_from_name("org", "x")


def test_band_001_merge_bands_at_the_boundaries():
    assert decide(0.85) == "auto-merge"
    assert decide(0.84) == "review"
    assert decide(0.82) == "review"
    assert decide(0.81) == "new"


async def test_prov_001_writes_without_provenance_are_rejected():
    with pytest.raises(MissingProvenance):
        await world().upsert_entity(type="person", name="No Provenance", source=None)


async def test_idem_001_same_batch_twice_is_an_empty_diff():
    w = world()
    await w.ingest(OBSERVATIONS)
    shape = w.state_shape_canonical()
    second = await w.ingest(OBSERVATIONS)
    assert second.changed is False
    assert w.state_shape_canonical() == shape


async def test_idem_002_a_mutated_batch_changes_the_shape():
    w = world()
    await w.ingest(OBSERVATIONS)
    shape = w.state_shape_canonical()
    edited = IngestObservation(**{**OBSERVATIONS[0].__dict__, "title": OBSERVATIONS[0].title + " (edited)"})
    run = await w.ingest([edited, OBSERVATIONS[1]])
    assert run.changed is True
    assert w.state_shape_canonical() != shape


async def test_bitemp_001_superseding_edge_closes_the_old_one():
    w = world()
    at = lambda s: Provenance(kind="manual", at=s)  # noqa: E731
    await w.upsert_entity(type="player", external_key=("g", "p1"), source=at("2087-01-01T00:00:00.000Z"))
    await w.upsert_entity(type="team", external_key=("g", "a"), source=at("2087-01-01T00:00:00.000Z"))
    await w.upsert_entity(type="team", external_key=("g", "b"), source=at("2088-03-01T00:00:00.000Z"))
    await w.relate(from_id="player:g:p1", type="plays-for", to_id="team:g:a",
                   valid_from="2087-01-01T00:00:00.000Z", source=at("2087-01-01T00:00:00.000Z"))
    await w.relate(from_id="player:g:p1", type="plays-for", to_id="team:g:b",
                   valid_from="2088-03-01T00:00:00.000Z", source=at("2088-03-01T00:00:00.000Z"))
    assert [e.id for e in w.neighbors_of("player:g:p1", via="plays-for")] == ["team:g:b"]
    then = w.neighbors_of("player:g:p1", via="plays-for", at="2087-06-01T00:00:00.000Z")
    assert [e.id for e in then] == ["team:g:a"]


async def test_audit_001_every_mutation_writes_an_audit_entry_in_order():
    w = world()
    await w.upsert_entity(type="x", name="Audit One", source=Provenance(kind="manual", at="2026-01-01T00:00:00.000Z"))
    await w.upsert_entity(type="x", name="Audit Two", source=Provenance(kind="manual", at="2026-01-02T00:00:00.000Z"))
    audit = w.audit()
    assert len(audit) >= 2
    assert all(b.seq > a.seq for a, b in zip(audit, audit[1:]))
