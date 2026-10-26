"""app/trials — TRIALS module. Public surface.

Owns: Trials (cached by NCT id with eligibility hash), Criteria (keyed by eligibility hash).
Hides: Zetaris REST table vs direct HTTP, paging, rate limits, hashing, criteria splitting.
"""
from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import ClassVar, NewType

import httpx

from app import logfile
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
class ConditionLabel:
    """A Condition label and how many stored Open and Closed trials list it. Labels equal ignoring case and repeated
    whitespace are one label, shown as the spelling most of those Trials use."""
    label: str
    open: int
    closed: int

    @property
    def total(self) -> int:
        return self.open + self.closed


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
    dropped: tuple[NctId, ...] = ()  # Closed trials past the cutoff (not stored, or removed if an earlier run kept
                                     # them), and earlier-stored Trials now withdrawn, unlisted in Australia or in a
                                     # status neither Open nor Closed (removed)


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


__all__ = ["ingest", "load_snapshot", "trial", "criteria", "sites", "contacts", "outcomes", "page_url",
           "active_trials", "outcome_summary",
           "condition_labels", "search_condition_labels", "ConditionLabel", "label_key", "label_words",
           "selection", "Selection", "closed_trials_with_labels", "label_keys",
           "Trial", "Criterion", "TrialSite", "Contact", "TrialContacts", "CriterionKind",
           "OutcomeMeasure", "Outcomes", "OutcomeSummary", "PostedResult", "ResultValue", "Publication",
           "SavedPages", "LivePages",
           "NctId", "CriterionId", "SyncReport", "IngestReport", "ACTIVE_STATUSES", "CLOSED_STATUSES",
           "trial_columns", "trial_from_row", "active_filter", "listing_filter"]


def page_url(nct_id: str) -> str:
    """The Trial's page on ClinicalTrials.gov."""
    return f"https://clinicaltrials.gov/study/{nct_id}"


# Statuses a Re-scan judges. NOT_YET_RECRUITING counts: Australian sites often open after US ones.
ACTIVE_STATUSES = ("RECRUITING", "NOT_YET_RECRUITING", "ENROLLING_BY_INVITATION")

# Statuses of a Closed trial: it can no longer enrol, so it is shown for its Outcomes and contacts, never judged.
CLOSED_STATUSES = ("COMPLETED", "TERMINATED", "SUSPENDED", "ACTIVE_NOT_RECRUITING", "UNKNOWN")

# A Closed trial whose cutoff date (Trial.closed_on) is more than this many years before the ingest date is dropped.
CLOSED_YEARS_KEPT = 15

# A stored study is Open (ACTIVE_STATUSES) or Closed (CLOSED_STATUSES). Any other status is never stored: WITHDRAWN
# (withdrawn before enrolling anyone, not a Trial per the glossary) and the expanded access statuses (AVAILABLE,
# NO_LONGER_AVAILABLE, TEMPORARILY_NOT_AVAILABLE, APPROVED_FOR_MARKETING), which are neither joinable nor research.

# Submodules import the types above; imported here (after them) so the `criteria` function below wins the name.
from app.trials import criteria as splitting, ctgov, repo, summary as summaries  # noqa: E402

log = logging.getLogger(__name__)

# For other modules' SQL that joins the trial table (one SQL text per question, ctx.py): its columns, row mapping,
# the active filter and the Condition label filter (keys from label_keys), so no module restates them.
trial_columns = repo.trial_columns
trial_from_row = repo.to_trial
active_filter = repo.active_filter
listing_filter = repo.listing


async def ingest(ctx: Ctx, source: SavedPages | LivePages) -> IngestReport:
    """Record every Open or Closed study the source holds that has an Australian Trial site (ADR 0004), keeping only
    its Australian sites. A withdrawn study, or one in any other status (expanded access: AVAILABLE,
    NO_LONGER_AVAILABLE, ...), is not stored, nor is a Closed trial whose cutoff date is more than 15 years before the
    ingest date (ctx.now). A Trial an earlier run stored that this run finds in any of those cases, or with no
    Australian site left, is dropped: no longer listed or judged, its Verdicts kept as history (ADR 0002). Stores
    eligibility text and its hash only: no model call, and Criteria are split the first time they are asked for
    (`criteria`). Idempotent on NCT id and content: a second run over the same pages records nothing and reports every
    Trial unchanged."""
    from app.worldmodel import timeline

    name = "http" if isinstance(source, LivePages) else "saved_pages"
    logfile.step(log, "trials.ingest.started", source=name,
                 directory=None if isinstance(source, LivePages) else str(source.directory))
    if isinstance(source, LivePages):
        pages = await ctgov.fetch_pages(source, ctx.now().isoformat())
    else:
        pages = ctgov.read_pages(source)
    cutoff = _years_before(ctx.now().date(), CLOSED_YEARS_KEPT).isoformat()
    kept, dropped, to_drop = [], [], []
    for raw, fetched_at in pages:
        raw = ctgov.in_australia(raw)
        too_old = raw.status in CLOSED_STATUSES and (ctgov.to_trial(raw, "", fetched_at).closed_on or cutoff) < cutoff
        if raw.sites and raw.status in ACTIVE_STATUSES + CLOSED_STATUSES and not too_old:
            kept.append((raw, fetched_at))
            continue
        stored = await repo.trial(ctx.ui_reader, NctId(raw.nct_id))
        if stored is not None:
            to_drop.append(stored)
        if too_old or stored is not None:   # a study that was never a stored Trial here is not worth reporting
            dropped.append(NctId(raw.nct_id))
    report = await _record(ctx, kept, name)
    await timeline.drop_trials(ctx.wm, to_drop, ctx.now().isoformat())
    done = IngestReport(**vars(report), closed=tuple(NctId(raw.nct_id) for raw, _ in kept
                                                     if raw.status in CLOSED_STATUSES),
                        dropped=tuple(dropped))
    logfile.step(log, "trials.ingest.finished", source=name, fetched=done.fetched, new=list(done.new),
                 changed=list(done.changed), unchanged=len(done.unchanged), closed=list(done.closed),
                 dropped=list(done.dropped))
    return done


def _years_before(day, years: int):
    try:
        return day.replace(year=day.year - years)
    except ValueError:   # 29 February
        return day.replace(year=day.year - years, day=28)


async def load_snapshot(ctx: Ctx, directory) -> SyncReport:
    """Record the Trials saved under `directory` (ClinicalTrials.gov v2 study JSON, one file per Trial; the
    repo keeps data/trials_snapshot/) in place of the Australia-wide `ingest`. Like `ingest`, Criteria are split lazily.
    Unlike it, every site is kept: the snapshot is a dev and test seed, and the distance tests use its overseas sites.
    It seeds a Trial cache the ingest has not filled: once the ingest has recorded a Trial it records nothing, so an
    app restart never rolls an ingested Trial back to the older saved copy with all its sites.
    Idempotent: loading the same files again records nothing and reports every Trial unchanged."""
    if await repo.has_ingested(ctx.ui_reader):
        return SyncReport(fetched=0, new=(), changed=(), unchanged=(), source="snapshot")
    return await _record(ctx, ctgov.read_snapshot(directory), "snapshot")


async def _record(ctx: Ctx, studies: list[tuple[ctgov.RawStudy, str]], source: str) -> SyncReport:
    from app.worldmodel import timeline

    before = {s.nct_id: await repo.trial(ctx.ui_reader, NctId(s.nct_id)) for s, _ in studies}
    loaded = [timeline.LoadedTrial(trial=ctgov.to_trial(raw, source, fetched_at), sites=raw.sites,
                                   contacts=raw.contacts, outcomes=raw.outcomes) for raw, fetched_at in studies]
    report = await timeline.record_trials(ctx.wm, loaded, None)
    changed = {i.split(":", 1)[1] for i in report.changed_ids}
    ids = [one.trial.nct_id for one in loaded]
    return SyncReport(fetched=len(loaded), new=tuple(n for n in ids if before[n] is None),
                      changed=tuple(n for n in ids if before[n] is not None and n in changed),
                      unchanged=tuple(n for n in ids if n not in changed), source=source)


async def trial(ctx: Ctx, nct_id: NctId, *, for_agent: bool = False) -> Trial | None:
    """The Trial as last loaded (None for an unknown or dropped Trial). for_agent reads through Zetaris."""
    return await repo.trial(ctx.agent_reader if for_agent else ctx.ui_reader, nct_id)


async def active_trials(ctx: Ctx) -> list[Trial]:
    return await repo.active_trials(ctx.ui_reader)


def _newest_first(closed: list[Trial]) -> list[Trial]:
    return sorted(sorted(closed, key=lambda t: t.nct_id), key=lambda t: t.closed_on or "", reverse=True)


def label_key(label: str) -> str:
    """Condition labels are equal when they match ignoring case and repeated whitespace."""
    return " ".join(label.casefold().split())


def label_words(text: str) -> str:
    """A label's or search phrase's words: its runs of letters and digits, casefolded, one space apart. A phrase is
    in a label when its words appear in the label's, whole and adjacent."""
    return " ".join(re.findall(r"[a-z0-9]+", text.casefold()))


async def condition_labels(ctx: Ctx) -> list[ConditionLabel]:
    """Every distinct Condition label the stored, non-dropped Trials list, with how many Open and Closed trials list
    it; most used first, then alphabetically."""
    return _labels(await repo.condition_spellings(ctx.ui_reader))


def _labels(spellings: list[tuple[str, str, int, int]]) -> list[ConditionLabel]:
    """Spellings of one label key are one label, shown as the spelling most Trials use (then the first by code
    point), with the counts summed."""
    by_key: dict[str, list[tuple[str, int, int]]] = {}
    for key, label, open_, closed in spellings:
        by_key.setdefault(key, []).append((label, open_, closed))
    found = [ConditionLabel(min(ss, key=lambda s: (-(s[1] + s[2]), s[0]))[0], open=sum(s[1] for s in ss),
                            closed=sum(s[2] for s in ss)) for ss in by_key.values()]
    return sorted(found, key=lambda one: (-one.total, label_key(one.label)))


async def search_condition_labels(ctx: Ctx, phrases: list[str], *, limit: int) -> list[ConditionLabel]:
    """The Condition labels containing any of the phrases as whole words ("cruciate ligament" finds "Anterior Cruciate
    Ligament Rupture", "injur" finds nothing), at most `limit`, most used first."""
    words = [w for w in dict.fromkeys(label_words(p) for p in phrases) if w]
    return _labels(await repo.condition_spellings(ctx.ui_reader, words))[:limit] if words else []


@dataclass(frozen=True)
class Selection:
    """The Trials a Condition term selects (ADR 0005): the stored Open trials (judged and listed) and Closed trials
    (listed, never judged) listing one of its labels, equal ignoring case and repeated whitespace. Selection.EMPTY
    without a Condition term."""
    open: frozenset[NctId]
    closed: frozenset[NctId]
    EMPTY: ClassVar[Selection]


Selection.EMPTY = Selection(open=frozenset(), closed=frozenset())


async def selection(ctx: Ctx, condition_term: tuple[str, ...] | None) -> Selection:
    """The Trials the Condition term selects; Selection.EMPTY (and no read) with none."""
    if not condition_term:
        return Selection.EMPTY
    found = await repo.listing_any(ctx.ui_reader, label_keys(condition_term))
    return Selection(open=frozenset(n for n, status in found if status in ACTIVE_STATUSES),
                     closed=frozenset(n for n, status in found if status in CLOSED_STATUSES))


def label_keys(labels: Sequence[str]) -> list[str]:
    """The distinct label keys of a Condition term's labels, in order: the parameters of listing_filter."""
    return list(dict.fromkeys(label_key(label) for label in labels))


async def closed_trials_with_labels(ctx: Ctx, condition_term: tuple[str, ...] | None) -> list[Trial]:
    """The Closed trials the Condition term selects (Selection.closed), newest first by cutoff date (Trial.closed_on);
    none without a Condition term. Never judged: they have no Criterion results or Verdict (ADR 0004)."""
    closed = (await selection(ctx, condition_term)).closed
    return _newest_first(await repo.trials_by_id(ctx.ui_reader, sorted(closed)))


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

    t = await trial(ctx, nct_id, for_agent=True)
    o = await outcomes(ctx, nct_id, for_agent=True)   # the model's input, read through Zetaris (ADR 0001)
    if t is None or o is None:
        return None
    key = summaries.outcomes_hash(o)
    cached = await repo.outcome_summary(ctx.ui_reader, nct_id, key)
    if cached is not None:
        return cached
    written = await llm.complete(ctx, llm.Lane.FAST, system=summaries.SYSTEM, user=summaries.prompt(t, o),
                                 out=summaries.Written, run_id=None)
    summary = OutcomeSummary(text=written.value.summary.strip(), outcomes_hash=key)
    logfile.step(log, "trials.outcome_summary.drafted", nct_id=nct_id, outcomes_hash=key,
                 model_answered=written.model_answered)
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
