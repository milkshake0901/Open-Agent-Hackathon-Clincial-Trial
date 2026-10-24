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


__all__ = ["sync", "load_snapshot", "trial", "criteria", "active_trials", "studies_condition", "Trial", "Criterion", "CriterionKind",
           "NctId", "CriterionId", "SyncReport", "ACTIVE_STATUSES"]

# Statuses a Re-scan judges. NOT_YET_RECRUITING counts: Australian sites often open after US ones.
ACTIVE_STATUSES = ("RECRUITING", "NOT_YET_RECRUITING", "ENROLLING_BY_INVITATION")

_STOP_WORDS = frozenset({"of", "the", "and", "with", "in", "a", "an"})


def _words(text: str) -> frozenset[str]:
    import re
    return frozenset(w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _STOP_WORDS)


def studies_condition(trial: Trial, term: str) -> bool:
    """Does the Trial list this condition (#14: a confirmed diagnosis term selects which snapshot Trials are judged)?
    Word-set containment either way against each listed condition, ignoring case, punctuation and filler words:
    "lung cancer" and "non-small cell lung cancer stage iv" both match "Non-Small Cell Lung Cancer"; "breast cancer"
    does not. No MeSH or synonym expansion yet (a live condition search is trials.sync)."""
    want = _words(term)
    return bool(want) and any(want <= have or have <= want for have in map(_words, trial.conditions) if have)


# Submodules import the types above; imported here (after them) so the `criteria` function below wins the name.
from app.trials import criteria as splitting, ctgov, repo  # noqa: E402


async def sync(ctx: Ctx, condition: str, location: str, *, max_trials: int = 30) -> SyncReport:
    """Fetch from ClinicalTrials.gov (Zetaris REST table first, HTTP fallback), upsert trials, split Criteria
    only for new/changed hashes. Idempotent: same upstream text → unchanged, no model calls.
    # TODO: ctgov.fetch(...) → for each: hash; compare with repo.trial(); if new/changed: criteria.split (deterministic,
    #       LLM fast lane only if <2 items) → timeline.record_trials(ctx.wm, ...) (World Model ingest keyed by NCT; changed_ids = new or edited Trials)
    """
    raise NotImplementedError


async def load_snapshot(ctx: Ctx, directory) -> SyncReport:
    """Record the Trials saved under `directory` (ClinicalTrials.gov v2 study JSON, one file per Trial; the
    repo keeps data/trials_snapshot/) in place of a live sync. Criteria are split deterministically. Idempotent:
    loading the same files again records nothing and reports every Trial unchanged."""
    from app.worldmodel import timeline

    studies = ctgov.read_snapshot(directory)
    before = {s.nct_id: await repo.trial(ctx.ui_reader, NctId(s.nct_id)) for s, _ in studies}
    loaded = []
    for raw, fetched_at in studies:
        t = ctgov.to_trial(raw, "snapshot", fetched_at)
        loaded.append((t, splitting.split_deterministic(t.nct_id, t.eligibility_hash, t.eligibility_text)))
    report = await timeline.record_trials(ctx.wm, loaded, None)
    changed = {i.split(":", 1)[1] for i in report.changed_ids}
    return SyncReport(fetched=len(loaded),
                      new=tuple(t.nct_id for t, _ in loaded if before[t.nct_id] is None),
                      changed=tuple(t.nct_id for t, _ in loaded if before[t.nct_id] is not None and t.nct_id in changed),
                      unchanged=tuple(t.nct_id for t, _ in loaded if t.nct_id not in changed), source="snapshot")


async def trial(ctx: Ctx, nct_id: NctId) -> Trial | None:
    return await repo.trial(ctx.ui_reader, nct_id)


async def active_trials(ctx: Ctx) -> list[Trial]:
    return await repo.active_trials(ctx.ui_reader)


async def criteria(ctx: Ctx, nct_id: NctId, *, for_agent: bool = False) -> tuple[Criterion, ...]:
    """Criteria for the trial's CURRENT eligibility hash, in ordinal order. for_agent reads through Zetaris."""
    reader = ctx.agent_reader if for_agent else ctx.ui_reader
    t = await repo.trial(reader, nct_id)
    return await repo.criteria(reader, nct_id, t.eligibility_hash) if t else ()
