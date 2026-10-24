"""app/worldmodel/stable_ids.py — deterministic ids (spec: engines/world-model/docs/stable-ids.md).

Same input, same id, on every machine and every replay. This is what makes ingest idempotent
and lets a crash-and-retry append be rejected as a duplicate.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import uuid
from typing import Any

_WS = re.compile(r"\s+")
_NAMESPACE = uuid.UUID("6f1c1d6e-2b7a-4c1e-9f3e-7d5a0b8c4e21")


def normalize_name(name: str) -> str:
    """NFKD, strip combining marks, NBSP → space, collapse whitespace, lowercase (conformance sid-001).
    Must NOT over-normalise: "Acme Corp" and "Acme Corporation" stay distinct (sid-002)."""
    decomposed = unicodedata.normalize("NFKD", name.replace("\u00a0", " "))
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return _WS.sub(" ", stripped).strip().lower()


def entity_id_from_name(type: str, name: str) -> str:
    """"<type>:<normalize_name(name)>" style key; the type participates (sid-002)."""
    return f"{type}:{normalize_name(name)}"


def canonical_json(value: Any) -> str:
    """Sorted keys, no whitespace; the input to every content hash."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def fact_id(about: str, predicate: str, value: Any, observed_at: str, checksum: str | None) -> str:
    """Content-derived: the same Fact drafted twice from the same Document page dedupes."""
    digest = sha256_hex(canonical_json([about, predicate, value, observed_at, checksum]))
    return f"fact:{digest[:32]}"


def event_id(actor: str, cause: str, index: int) -> str:
    """uuid5(actor, cause, index). A duplicate append after a crash hits the unique key and is ignored."""
    return str(uuid.uuid5(_NAMESPACE, f"{actor}|{cause}|{index}"))
