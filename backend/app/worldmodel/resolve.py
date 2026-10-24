"""app/worldmodel/resolve.py — entity resolution banding (spec: reference/src/resolve.ts).

TrialMatch uses this to decide whether two subject names from different Documents are the same
thing ("Haemoglobin" vs "Hb") before the critic compares their values.
"""
from __future__ import annotations

from typing import Literal

from app.worldmodel.stable_ids import normalize_name

AUTO_MERGE_AT = 0.85
REVIEW_FROM = 0.82

Decision = Literal["auto-merge", "review", "new"]


def decide(similarity: float) -> Decision:
    """>= 0.85 auto-merge; [0.82, 0.85) review; below 0.82 new (conformance band-001, boundaries inclusive)."""
    if similarity >= AUTO_MERGE_AT:
        return "auto-merge"
    if similarity >= REVIEW_FROM:
        return "review"
    return "new"


def name_similarity(a: str, b: str) -> float:
    """Normalised Levenshtein over normalize_name(a), normalize_name(b)."""
    x, y = normalize_name(a), normalize_name(b)
    if not x and not y:
        return 1.0
    prev = list(range(len(y) + 1))
    for i, cx in enumerate(x, 1):
        cur = [i]
        for j, cy in enumerate(y, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (cx != cy)))
        prev = cur
    return 1.0 - prev[-1] / max(len(x), len(y))
