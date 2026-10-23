"""app/worldmodel/resolve.py — entity resolution banding (spec: reference/src/resolve.ts).

TrialMatch uses this to decide whether two subject names from different Documents are the same
thing ("Haemoglobin" vs "Hb") before the critic compares their values.
"""
from __future__ import annotations

from typing import Literal

AUTO_MERGE_AT = 0.85
REVIEW_FROM = 0.82

Decision = Literal["auto-merge", "review", "new"]


def decide(similarity: float) -> Decision:
    """>= 0.85 auto-merge; [0.82, 0.85) review; below 0.82 new (conformance band-001, boundaries inclusive)."""
    raise NotImplementedError


def name_similarity(a: str, b: str) -> float:
    """Normalised Levenshtein over normalize_name(a), normalize_name(b)."""
    raise NotImplementedError
