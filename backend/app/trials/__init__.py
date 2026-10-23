"""app/trials — TRIALS module. Public surface.

Owns: Trials (cached by NCT id with eligibility hash), Criteria (keyed by eligibility hash).
Hides: Zetaris REST table vs direct HTTP, paging, rate limits, hashing, criteria splitting.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import NewType

from app.ctx import Ctx

NctId = NewType("NctId", str)
CriterionId = NewType("CriterionId", str)   # f"{nct}:{eligibility_hash[:8]}:{ordinal}" — stable across re-splits of identical text


class CriterionKind(StrEnum):
    INCLUSION = "inclusion"
    EXCLUSION = "exclusion"


@dataclass(frozen=True)
class Trial:
    nct_id: NctId
    title: str
    conditions: tuple[str, ...]
    status: str                  # RECRUITING etc.; active = status in a small allowlist
    eligibility_text: str
    eligibility_hash: str        # sha256 of normalised eligibility_text
    fetched_at: str
    source: str                  # "zetaris" | "http" — logged for the sponsor-tech story


@dataclass(frozen=True)
class Criterion:
    id: CriterionId
    nct_id: NctId
    eligibility_hash: str
    kind: CriterionKind
    ordinal: int
    text: str


@dataclass(frozen=True)
class SyncReport:
    fetched: int
    new: tuple[NctId, ...]
    changed: tuple[NctId, ...]       # eligibility hash differs from cached → Criteria re-split, Verdicts stale
    unchanged: tuple[NctId, ...]
    source: str


__all__ = ["sync", "trial", "criteria", "active_trials", "Trial", "Criterion", "CriterionKind", "NctId", "CriterionId", "SyncReport"]


async def sync(ctx: Ctx, condition: str, location: str, *, max_trials: int = 30) -> SyncReport:
    """Fetch from ClinicalTrials.gov (Zetaris REST table first, HTTP fallback), upsert trials, split Criteria
    only for new/changed hashes. Idempotent: same upstream text → unchanged, no model calls.
    # TODO: ctgov.fetch(...) → for each: hash; compare with repo.trial(); if new/changed: criteria.split (deterministic,
    #       LLM fast lane only if <2 items) → timeline.record_trials(ctx.wm, ...) (World Model ingest keyed by NCT; changed_ids = new or edited Trials)
    """
    raise NotImplementedError


async def trial(ctx: Ctx, nct_id: NctId) -> Trial | None:
    raise NotImplementedError


async def active_trials(ctx: Ctx) -> list[Trial]:
    raise NotImplementedError


async def criteria(ctx: Ctx, nct_id: NctId, *, for_agent: bool = False) -> tuple[Criterion, ...]:
    """Criteria for the trial's CURRENT eligibility hash. for_agent reads through Zetaris."""
    raise NotImplementedError
