"""app/trials — TRIALS module. Public surface.

Owns: Trials (cached by NCT id with eligibility hash), Criteria (keyed by eligibility hash).
Hides: Zetaris REST table vs direct HTTP, paging, rate limits, hashing, criteria splitting.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
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
class TrialSite:
    """One of a Trial's locations as ClinicalTrials.gov lists it. lat/lon is the registry's geoPoint (None if absent)."""
    facility: str
    city: str
    country: str
    status: str                  # per-site recruitment status, e.g. RECRUITING, NOT_YET_RECRUITING; "" if not given
    lat: float | None
    lon: float | None


@dataclass(frozen=True)
class SyncReport:
    fetched: int
    new: tuple[NctId, ...]
    changed: tuple[NctId, ...]       # eligibility hash differs from cached → Criteria re-split, Verdicts stale
    unchanged: tuple[NctId, ...]
    source: str


@dataclass(frozen=True)
class SavedPages:
    """An ingest source: ClinicalTrials.gov v2 `GET /api/v2/studies` responses saved under `directory`, one page
    per JSON file (the response body, or the cached envelope {url, fetched_at, body}), read in file-name order."""
    directory: Path


__all__ = ["sync", "ingest", "load_snapshot", "trial", "criteria", "sites", "active_trials", "studies_condition",
           "Trial", "Criterion", "TrialSite", "CriterionKind", "SavedPages",
           "NctId", "CriterionId", "SyncReport", "ACTIVE_STATUSES", "trial_columns", "trial_from_row", "active_filter"]

# Statuses a Re-scan judges. NOT_YET_RECRUITING counts: Australian sites often open after US ones.
ACTIVE_STATUSES = ("RECRUITING", "NOT_YET_RECRUITING", "ENROLLING_BY_INVITATION")

# A study withdrawn before enrolling anyone is not a Trial (glossary) and is never stored.
WITHDRAWN = "WITHDRAWN"

_STOP_WORDS = frozenset({"of", "the", "and", "with", "in", "a", "an"})


def _words(text: str) -> frozenset[str]:
    import re
    return frozenset(w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _STOP_WORDS)


def studies_condition(trial: Trial, condition_term: str) -> bool:
    """Does the Trial list this condition (#14: a confirmed diagnosis term selects which snapshot Trials are judged)?
    Word-set containment either way against each listed condition, ignoring case, punctuation and filler words:
    "lung cancer" and "non-small cell lung cancer stage iv" both match "Non-Small Cell Lung Cancer"; "breast cancer"
    does not. No MeSH or synonym expansion yet (a live condition search is trials.sync)."""
    want = _words(condition_term)
    return bool(want) and any(want <= have or have <= want for have in map(_words, trial.conditions) if have)


# Submodules import the types above; imported here (after them) so the `criteria` function below wins the name.
from app.trials import criteria as splitting, ctgov, repo  # noqa: E402

# For other modules' SQL that joins the trial table (one SQL text per question, ctx.py): its columns, row mapping
# and the active filter, so no module restates them.
trial_columns = repo.trial_columns
trial_from_row = repo.to_trial
active_filter = repo.active_filter


async def sync(ctx: Ctx, condition: str, location: str, *, max_trials: int = 30) -> SyncReport:
    """Fetch from ClinicalTrials.gov (Zetaris REST table first, HTTP fallback), upsert trials, split Criteria
    only for new/changed hashes. Idempotent: same upstream text → unchanged, no model calls.
    # TODO: ctgov.fetch(...) → for each: hash; compare with repo.trial(); if new/changed: criteria.split (deterministic,
    #       LLM fast lane only if <2 items) → timeline.record_trials(ctx.wm, ...) (World Model ingest keyed by NCT; changed_ids = new or edited Trials)
    """
    raise NotImplementedError


async def ingest(ctx: Ctx, source: SavedPages) -> SyncReport:
    """Record every study the source holds that has an Australian Trial site (ADR 0004), keeping only its
    Australian sites and never a withdrawn study. Stores eligibility text and its hash only: no model call, and
    Criteria are split the first time they are asked for (`criteria`). Idempotent on NCT id and content: a second
    run over the same pages records nothing and reports every Trial unchanged."""
    studies = [(ctgov.in_australia(raw), fetched_at) for raw, fetched_at in ctgov.read_pages(source)]
    return await _record(ctx, [(raw, fetched_at) for raw, fetched_at in studies
                               if raw.sites and raw.status != WITHDRAWN], "saved_pages")


async def load_snapshot(ctx: Ctx, directory) -> SyncReport:
    """Record the Trials saved under `directory` (ClinicalTrials.gov v2 study JSON, one file per Trial; the
    repo keeps data/trials_snapshot/) in place of a live sync. Like `ingest`, Criteria are split lazily.
    Idempotent: loading the same files again records nothing and reports every Trial unchanged."""
    return await _record(ctx, ctgov.read_snapshot(directory), "snapshot")


async def _record(ctx: Ctx, studies: list[tuple[ctgov.RawStudy, str]], source: str) -> SyncReport:
    from app.worldmodel import timeline

    before = {s.nct_id: await repo.trial(ctx.ui_reader, NctId(s.nct_id)) for s, _ in studies}
    loaded = [(ctgov.to_trial(raw, source, fetched_at), (), raw.sites) for raw, fetched_at in studies]
    report = await timeline.record_trials(ctx.wm, loaded, None)
    changed = {i.split(":", 1)[1] for i in report.changed_ids}
    return SyncReport(fetched=len(loaded),
                      new=tuple(t.nct_id for t, *_ in loaded if before[t.nct_id] is None),
                      changed=tuple(t.nct_id for t, *_ in loaded if before[t.nct_id] is not None and t.nct_id in changed),
                      unchanged=tuple(t.nct_id for t, *_ in loaded if t.nct_id not in changed), source=source)


async def trial(ctx: Ctx, nct_id: NctId) -> Trial | None:
    return await repo.trial(ctx.ui_reader, nct_id)


async def active_trials(ctx: Ctx) -> list[Trial]:
    return await repo.active_trials(ctx.ui_reader)


async def sites(ctx: Ctx, nct_id: NctId) -> tuple[TrialSite, ...]:
    """The Trial's locations as last loaded, in registry order (empty for an unknown Trial)."""
    return await repo.sites(ctx.ui_reader, nct_id)


async def criteria(ctx: Ctx, nct_id: NctId, *, for_agent: bool = False) -> tuple[Criterion, ...]:
    """Criteria for the trial's CURRENT eligibility hash, in ordinal order. for_agent reads through Zetaris.
    The ingest stores only eligibility text and its hash (ADR 0004), so the first ask for a hash splits the text
    deterministically and records the Criteria; later asks read them back."""
    from app.worldmodel import timeline

    reader = ctx.agent_reader if for_agent else ctx.ui_reader
    t = await repo.trial(reader, nct_id)
    if t is None:
        return ()
    stored = await repo.criteria(reader, nct_id, t.eligibility_hash)
    if stored:
        return stored
    split = splitting.split_deterministic(t.nct_id, t.eligibility_hash, t.eligibility_text)
    if split:
        await timeline.record_criteria(ctx.wm, t, split)
    return split
