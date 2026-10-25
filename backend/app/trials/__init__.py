"""app/trials — TRIALS module. Public surface.

Owns: Trials (cached by NCT id with eligibility hash), Criteria (keyed by eligibility hash).
Hides: Zetaris REST table vs direct HTTP, paging, rate limits, hashing, criteria splitting.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import NewType

import httpx

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
    primary_completion_date: str | None = None   # ISO dates from the registry; a month-only date is its 1st
    completion_date: str | None = None
    last_update_date: str | None = None

    @property
    def is_open(self) -> bool:
        """An Open trial (recruiting, not yet recruiting or enrolling by invitation): the only kind a Re-scan judges.
        Any other stored Trial is a Closed trial, never judged; one that closed after it was judged keeps its Verdicts
        and is shown as no longer recruiting (ADR 0004)."""
        return self.status in ACTIVE_STATUSES

    @property
    def closed_on(self) -> str | None:
        """A Closed trial's cutoff date (ADR 0004): primary completion, else completion, else last update."""
        return self.primary_completion_date or self.completion_date or self.last_update_date


@dataclass(frozen=True)
class Criterion:
    id: CriterionId
    nct_id: NctId
    eligibility_hash: str
    kind: CriterionKind
    ordinal: int
    text: str


@dataclass(frozen=True)
class Contact:
    """A person or desk ClinicalTrials.gov names for a Trial or Trial site; fields it does not give are ""."""
    name: str
    role: str                    # registry role, e.g. CONTACT, PRINCIPAL_INVESTIGATOR, STUDY_DIRECTOR, SPONSOR
    email: str = ""
    phone: str = ""
    affiliation: str = ""
    title: str = ""


@dataclass(frozen=True)
class TrialContacts:
    """Who to contact about a Trial (#27), besides each Trial site's own contacts (TrialSite.contacts)."""
    sponsor: str                         # lead sponsor's name; "" if not given
    responsible_party: Contact | None    # a SPONSOR responsible party is named by the lead sponsor
    central: tuple[Contact, ...]         # central contacts
    officials: tuple[Contact, ...]       # overall officials
    page_url: str                        # the Trial's ClinicalTrials.gov page


@dataclass(frozen=True)
class OutcomeMeasure:
    """One planned outcome measure as ClinicalTrials.gov lists it; fields it does not give are ""."""
    measure: str
    description: str = ""
    time_frame: str = ""


@dataclass(frozen=True)
class ResultValue:
    """One group's posted value for an outcome measure; fields the registry does not give are ""."""
    group: str                   # the arm or group's title
    value: str
    spread: str = ""             # e.g. standard deviation, per the measure's dispersion type
    lower: str = ""              # confidence or range limits
    upper: str = ""
    label: str = ""              # the class and category the value is for, when the measure is split ("" if not)


@dataclass(frozen=True)
class PostedResult:
    """One outcome measure's posted results from the registry's results section."""
    type: str                    # PRIMARY, SECONDARY, OTHER_PRE_SPECIFIED or POST_HOC
    title: str
    description: str = ""
    time_frame: str = ""
    unit: str = ""               # unit of measure
    param_type: str = ""         # e.g. MEDIAN, MEAN, COUNT_OF_PARTICIPANTS
    values: tuple[ResultValue, ...] = ()


@dataclass(frozen=True)
class Publication:
    """A reference the registry links to a Trial."""
    pmid: str                    # PubMed id; "" when the registry gives only a citation
    type: str                    # RESULT (reports the Trial's findings), BACKGROUND or DERIVED
    citation: str

    @property
    def url(self) -> str:
        """The publication's PubMed page; "" without a PubMed id."""
        return f"https://pubmed.ncbi.nlm.nih.gov/{self.pmid}/" if self.pmid else ""


@dataclass(frozen=True)
class Outcomes:
    """What a Trial measured or found (#25, glossary: Outcome), as last loaded."""
    primary: tuple[OutcomeMeasure, ...]      # planned outcome measures, in registry order
    secondary: tuple[OutcomeMeasure, ...]
    other: tuple[OutcomeMeasure, ...]
    has_results: bool = False                # the registry's has-results flag
    results: tuple[PostedResult, ...] = ()   # posted results, in registry order
    publications: tuple[Publication, ...] = ()


@dataclass(frozen=True)
class OutcomeSummary:
    """A plain-language summary of a Closed trial's Outcomes (#26), written by the model for the Outcomes it names."""
    text: str
    outcomes_hash: str           # the Outcome content hash it was written for (sha256 of the Outcomes' canonical JSON)


@dataclass(frozen=True)
class TrialSite:
    """One of a Trial's locations as ClinicalTrials.gov lists it. lat/lon is the registry's geoPoint (None if absent)."""
    facility: str
    city: str
    country: str
    status: str                  # per-site recruitment status, e.g. RECRUITING, NOT_YET_RECRUITING; "" if not given
    lat: float | None
    lon: float | None
    contacts: tuple[Contact, ...] = ()


@dataclass(frozen=True)
class SyncReport:
    fetched: int
    new: tuple[NctId, ...]
    changed: tuple[NctId, ...]       # eligibility hash differs from cached → Criteria re-split, Verdicts stale
    unchanged: tuple[NctId, ...]
    source: str


@dataclass(frozen=True)
class IngestReport(SyncReport):
    closed: tuple[NctId, ...] = ()   # Closed trials recorded (new, changed or unchanged), within the 15-year cutoff
    dropped: tuple[NctId, ...] = ()  # Closed trials past the cutoff: not stored, or removed if an earlier run kept them


@dataclass(frozen=True)
class SavedPages:
    """An ingest source: ClinicalTrials.gov v2 `GET /api/v2/studies` responses saved under `directory`, one page
    per JSON file (the response body, or the cached envelope {url, fetched_at, body}), read in file-name order."""
    directory: Path


@dataclass(frozen=True)
class LivePages:
    """An ingest source: the live ClinicalTrials.gov v2 API, `GET /api/v2/studies` filtered to Australia and paged
    by pageToken. Requests are spaced to stay under `requests_per_minute` (the API allows about 50) and a transient
    failure (timeout, connection error, 429, 5xx) is retried up to `retries` times. `transport` and `sleep` are
    for tests: recorded pages, and pacing that is observed rather than waited for."""
    base_url: str = "https://clinicaltrials.gov/api/v2"
    page_size: int = 1000
    requests_per_minute: int = 40
    retries: int = 4
    timeout_s: float = 60.0
    transport: httpx.AsyncBaseTransport | None = None
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep


__all__ = ["sync", "ingest", "load_snapshot", "trial", "criteria", "sites", "contacts", "outcomes", "page_url",
           "active_trials", "closed_trials", "outcome_summary",
           "studies_condition", "Trial", "Criterion", "TrialSite", "Contact", "TrialContacts", "CriterionKind",
           "OutcomeMeasure", "Outcomes", "OutcomeSummary", "PostedResult", "ResultValue", "Publication",
           "SavedPages", "LivePages",
           "NctId", "CriterionId", "SyncReport", "IngestReport", "ACTIVE_STATUSES", "CLOSED_STATUSES",
           "trial_columns", "trial_from_row", "active_filter"]


def page_url(nct_id: str) -> str:
    """The Trial's page on ClinicalTrials.gov."""
    return f"https://clinicaltrials.gov/study/{nct_id}"


# Statuses a Re-scan judges. NOT_YET_RECRUITING counts: Australian sites often open after US ones.
ACTIVE_STATUSES = ("RECRUITING", "NOT_YET_RECRUITING", "ENROLLING_BY_INVITATION")

# Statuses of a Closed trial: it can no longer enrol, so it is shown for its Outcomes and contacts, never judged.
CLOSED_STATUSES = ("COMPLETED", "TERMINATED", "SUSPENDED", "ACTIVE_NOT_RECRUITING", "UNKNOWN")

# A Closed trial whose cutoff date (Trial.closed_on) is more than this many years before the ingest date is dropped.
CLOSED_YEARS_KEPT = 15

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
from app.trials import criteria as splitting, ctgov, repo, summary as summaries  # noqa: E402

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


async def ingest(ctx: Ctx, source: SavedPages | LivePages) -> IngestReport:
    """Record every study the source holds that has an Australian Trial site (ADR 0004), keeping only its
    Australian sites and never a withdrawn study. A Closed trial whose cutoff date is more than 15 years before
    the ingest date (ctx.now) is not stored, and is removed if an earlier run stored it. Stores eligibility text and
    its hash only: no model call, and Criteria are split the first time they are asked for (`criteria`).
    Idempotent on NCT id and content: a second run over the same pages records nothing and reports every Trial
    unchanged."""
    from app.worldmodel import timeline

    if isinstance(source, LivePages):
        pages, name = await ctgov.fetch_pages(source, ctx.now().isoformat()), "http"
    else:
        pages, name = ctgov.read_pages(source), "saved_pages"
    cutoff = _years_before(ctx.now().date(), CLOSED_YEARS_KEPT).isoformat()
    kept, too_old = [], []
    for raw, fetched_at in pages:
        raw = ctgov.in_australia(raw)
        if not raw.sites or raw.status == WITHDRAWN:
            continue
        closed_on = ctgov.to_trial(raw, "", fetched_at).closed_on
        if raw.status not in ACTIVE_STATUSES and closed_on is not None and closed_on < cutoff:
            too_old.append((raw, fetched_at))
        else:
            kept.append((raw, fetched_at))
    report = await _record(ctx, kept, name)
    stored = [t for t in [await repo.trial(ctx.ui_reader, NctId(raw.nct_id)) for raw, _ in too_old] if t is not None]
    await timeline.drop_trials(ctx.wm, stored, ctx.now().isoformat())
    return IngestReport(**vars(report), closed=tuple(NctId(raw.nct_id) for raw, _ in kept
                                                      if raw.status not in ACTIVE_STATUSES),
                        dropped=tuple(NctId(raw.nct_id) for raw, _ in too_old))


def _years_before(day, years: int):
    try:
        return day.replace(year=day.year - years)
    except ValueError:   # 29 February
        return day.replace(year=day.year - years, day=28)


async def load_snapshot(ctx: Ctx, directory) -> SyncReport:
    """Record the Trials saved under `directory` (ClinicalTrials.gov v2 study JSON, one file per Trial; the
    repo keeps data/trials_snapshot/) in place of a live sync. Like `ingest`, Criteria are split lazily.
    Idempotent: loading the same files again records nothing and reports every Trial unchanged."""
    return await _record(ctx, ctgov.read_snapshot(directory), "snapshot")


async def _record(ctx: Ctx, studies: list[tuple[ctgov.RawStudy, str]], source: str) -> SyncReport:
    from app.worldmodel import timeline

    before = {s.nct_id: await repo.trial(ctx.ui_reader, NctId(s.nct_id)) for s, _ in studies}
    loaded = [(ctgov.to_trial(raw, source, fetched_at), (), raw.sites, raw.contacts, raw.outcomes)
              for raw, fetched_at in studies]
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


async def closed_trials(ctx: Ctx, condition_term: str) -> list[Trial]:
    """Closed trials that study this Condition term (the same `studies_condition` matching as Open trials), newest
    first by cutoff date (Trial.closed_on). Never judged: they have no Criterion results or Verdict (ADR 0004)."""
    found = [t for t in await repo.closed_trials(ctx.ui_reader) if studies_condition(t, condition_term)]
    return sorted(sorted(found, key=lambda t: t.nct_id), key=lambda t: t.closed_on or "", reverse=True)


async def sites(ctx: Ctx, nct_id: NctId) -> tuple[TrialSite, ...]:
    """The Trial's locations as last loaded, in registry order (empty for an unknown Trial)."""
    return await repo.sites(ctx.ui_reader, nct_id)


async def contacts(ctx: Ctx, nct_id: NctId) -> TrialContacts | None:
    """Who to contact about the Trial as last loaded (None for an unknown Trial); its sites' contacts are on `sites`."""
    if await repo.trial(ctx.ui_reader, nct_id) is None:
        return None
    return await repo.contacts(ctx.ui_reader, nct_id)


async def outcomes(ctx: Ctx, nct_id: NctId, *, for_agent: bool = False) -> Outcomes | None:
    """The Trial's Outcomes as last loaded (None for an unknown Trial). for_agent reads through Zetaris."""
    reader = ctx.agent_reader if for_agent else ctx.ui_reader
    if await repo.trial(reader, nct_id) is None:
        return None
    return await repo.outcomes(reader, nct_id)


async def outcome_summary(ctx: Ctx, nct_id: NctId) -> OutcomeSummary | None:
    """A plain-language summary of the Closed trial's Outcomes, written lazily (never at ingest): the first ask makes
    one fast-lane model call (not traced to a run) and records the summary keyed by NCT id and Outcome content hash;
    later asks for unchanged Outcomes read it back with no model call. None for an unknown Trial. Raises
    llm.LlmUnavailable."""
    from app import llm
    from app.worldmodel import timeline

    t = await repo.trial(ctx.ui_reader, nct_id)
    if t is None:
        return None
    o = await repo.outcomes(ctx.ui_reader, nct_id)
    key = summaries.outcomes_hash(o)
    cached = await repo.outcome_summary(ctx.ui_reader, nct_id, key)
    if cached is not None:
        return cached
    written = await llm.complete(ctx, llm.Lane.FAST, system=summaries.SYSTEM, user=summaries.prompt(t, o),
                                 out=summaries.Written, run_id=None)
    summary = OutcomeSummary(text=written.value.summary.strip(), outcomes_hash=key)
    await timeline.record_outcome_summary(ctx.wm, t, summary, written.model_answered, ctx.now().isoformat())
    return summary


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
