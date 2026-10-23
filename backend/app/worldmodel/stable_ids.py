"""app/worldmodel/stable_ids.py — deterministic ids (spec: engines/world-model/docs/stable-ids.md).

Same input, same id, on every machine and every replay. This is what makes ingest idempotent
and lets a crash-and-retry append be rejected as a duplicate.
"""
from __future__ import annotations

from typing import Any


def normalize_name(name: str) -> str:
    """NFKD, strip combining marks, NBSP → space, collapse whitespace, lowercase (conformance sid-001).
    Must NOT over-normalise: "Acme Corp" and "Acme Corporation" stay distinct (sid-002)."""
    raise NotImplementedError


def entity_id_from_name(type: str, name: str) -> str:
    """"<type>:<normalize_name(name)>" style key; the type participates (sid-002)."""
    raise NotImplementedError


def canonical_json(value: Any) -> str:
    """Sorted keys, no whitespace; the input to every content hash."""
    raise NotImplementedError


def sha256_hex(text: str) -> str:
    raise NotImplementedError


def fact_id(about: str, predicate: str, value: Any, observed_at: str, checksum: str | None) -> str:
    """Content-derived: the same Fact drafted twice from the same Document page dedupes."""
    raise NotImplementedError


def event_id(actor: str, cause: str, index: int) -> str:
    """uuid5(actor, cause, index). A duplicate append after a crash hits the unique key and is ignored."""
    raise NotImplementedError
