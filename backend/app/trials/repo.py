"""app/trials/repo.py — SQL for trial and criterion. Reads only."""
from __future__ import annotations

from app.sql.reader import SqlReader
from app.trials import ACTIVE_STATUSES, Criterion, CriterionId, CriterionKind, NctId, TrialSite, Trial

_TRIAL_COLS = ("nct_id", "title", "conditions", "status", "eligibility_text", "eligibility_hash", "fetched_at", "source")


def trial_columns(alias: str = "") -> str:
    """The trial columns to_trial reads, qualified by `alias` when the query joins other tables."""
    return ", ".join(f"{alias}.{c}" if alias else c for c in _TRIAL_COLS)


def to_trial(r: dict) -> Trial:
    return Trial(nct_id=NctId(r["nct_id"]), title=r["title"], conditions=tuple(r["conditions"]), status=r["status"],
                 eligibility_text=r["eligibility_text"], eligibility_hash=r["eligibility_hash"],
                 fetched_at=r["fetched_at"].isoformat(), source=r["source"])


def active_filter(alias: str = "") -> str:
    """ANSI `status IN (...)` over the fixed allowlist (literals, so Zetaris needs no array parameter)."""
    col = f"{alias}.status" if alias else "status"
    return f"{col} IN ({', '.join(repr(s) for s in ACTIVE_STATUSES)})"


async def trial(reader: SqlReader, nct_id: NctId) -> Trial | None:
    rows = await reader.fetch(f"SELECT {trial_columns()} FROM {reader.table('trial')} WHERE nct_id = $1", (nct_id,))
    return to_trial(rows[0]) if rows else None


async def active_trials(reader: SqlReader) -> list[Trial]:
    rows = await reader.fetch(f"SELECT {trial_columns()} FROM {reader.table('trial')} WHERE {active_filter()} "
                              "ORDER BY nct_id")
    return [to_trial(r) for r in rows]


async def criteria(reader: SqlReader, nct_id: NctId, eligibility_hash: str) -> tuple[Criterion, ...]:
    rows = await reader.fetch(
        f"SELECT id, nct_id, eligibility_hash, kind, ordinal, text FROM {reader.table('criterion')} "
        "WHERE nct_id = $1 AND eligibility_hash = $2 ORDER BY ordinal", (nct_id, eligibility_hash))
    return tuple(Criterion(id=CriterionId(r["id"]), nct_id=NctId(r["nct_id"]), eligibility_hash=r["eligibility_hash"],
                           kind=CriterionKind(r["kind"]), ordinal=r["ordinal"], text=r["text"]) for r in rows)

async def sites(reader: SqlReader, nct_id: NctId) -> tuple[TrialSite, ...]:
    rows = await reader.fetch(f"SELECT facility, city, country, status, lat, lon FROM {reader.table('trial_site')} "
                              "WHERE nct_id = $1 ORDER BY ordinal", (nct_id,))
    return tuple(TrialSite(facility=r["facility"], city=r["city"], country=r["country"], status=r["status"],
                      lat=r["lat"], lon=r["lon"]) for r in rows)

# Trials, Criteria and Sites are NOT written here: app.worldmodel.timeline.record_trials (World Model ingest → projector).
