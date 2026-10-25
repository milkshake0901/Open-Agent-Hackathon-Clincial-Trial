"""app/trials/repo.py — SQL for trial and criterion. Reads only."""
from __future__ import annotations

from app.sql.reader import SqlReader
from app.trials import (ACTIVE_STATUSES, CLOSED_STATUSES, Contact, Criterion, CriterionId, CriterionKind, NctId,
                        OutcomeMeasure, Outcomes, PostedResult, Publication, ResultValue,
                        TrialContacts, TrialSite, Trial, page_url)

_TRIAL_COLS = ("nct_id", "title", "conditions", "status", "eligibility_text", "eligibility_hash", "fetched_at", "source",
               "primary_completion_date", "completion_date", "last_update_date")


def trial_columns(alias: str = "") -> str:
    """The trial columns to_trial reads, qualified by `alias` when the query joins other tables."""
    return ", ".join(f"{alias}.{c}" if alias else c for c in _TRIAL_COLS)


def to_trial(r: dict) -> Trial:
    return Trial(nct_id=NctId(r["nct_id"]), title=r["title"], conditions=tuple(r["conditions"]), status=r["status"],
                 eligibility_text=r["eligibility_text"], eligibility_hash=r["eligibility_hash"],
                 fetched_at=r["fetched_at"].isoformat(), source=r["source"],
                 primary_completion_date=_iso(r["primary_completion_date"]), completion_date=_iso(r["completion_date"]),
                 last_update_date=_iso(r["last_update_date"]))


def _iso(day) -> str | None:
    return day.isoformat() if day is not None else None


def active_filter(alias: str = "") -> str:
    """ANSI `status IN (...)` over the fixed allowlist (literals, so Zetaris needs no array parameter)."""
    col = f"{alias}.status" if alias else "status"
    return f"{col} IN ({', '.join(repr(s) for s in ACTIVE_STATUSES)})"


async def trial(reader: SqlReader, nct_id: NctId) -> Trial | None:
    rows = await reader.fetch(f"SELECT {trial_columns()} FROM {reader.table('trial')} WHERE nct_id = $1 AND NOT dropped",
                              (nct_id,))
    return to_trial(rows[0]) if rows else None


async def active_trials(reader: SqlReader) -> list[Trial]:
    rows = await reader.fetch(f"SELECT {trial_columns()} FROM {reader.table('trial')} WHERE {active_filter()} "
                              "ORDER BY nct_id")
    return [to_trial(r) for r in rows]


async def closed_trials(reader: SqlReader) -> list[Trial]:
    statuses = ", ".join(repr(s) for s in CLOSED_STATUSES)
    rows = await reader.fetch(f"SELECT {trial_columns()} FROM {reader.table('trial')} "
                              f"WHERE status IN ({statuses}) AND NOT dropped ORDER BY nct_id")
    return [to_trial(r) for r in rows]


async def criteria(reader: SqlReader, nct_id: NctId, eligibility_hash: str) -> tuple[Criterion, ...]:
    rows = await reader.fetch(
        f"SELECT id, nct_id, eligibility_hash, kind, ordinal, text FROM {reader.table('criterion')} "
        "WHERE nct_id = $1 AND eligibility_hash = $2 ORDER BY ordinal", (nct_id, eligibility_hash))
    return tuple(Criterion(id=CriterionId(r["id"]), nct_id=NctId(r["nct_id"]), eligibility_hash=r["eligibility_hash"],
                           kind=CriterionKind(r["kind"]), ordinal=r["ordinal"], text=r["text"]) for r in rows)

async def sites(reader: SqlReader, nct_id: NctId) -> tuple[TrialSite, ...]:
    rows = await reader.fetch(f"SELECT ordinal, facility, city, country, status, lat, lon "
                              f"FROM {reader.table('trial_site')} WHERE nct_id = $1 ORDER BY ordinal", (nct_id,))
    by_site: dict[int, list[Contact]] = {}
    for r in await _contact_rows(reader, nct_id):
        if r["kind"] == "site":
            by_site.setdefault(r["site_ordinal"], []).append(_contact(r))
    return tuple(TrialSite(facility=r["facility"], city=r["city"], country=r["country"], status=r["status"],
                      lat=r["lat"], lon=r["lon"], contacts=tuple(by_site.get(r["ordinal"], ()))) for r in rows)


async def contacts(reader: SqlReader, nct_id: NctId) -> TrialContacts:
    rows = [r for r in await _contact_rows(reader, nct_id) if r["kind"] != "site"]
    of = lambda kind: tuple(_contact(r) for r in rows if r["kind"] == kind)  # noqa: E731
    return TrialContacts(sponsor=next((c.name for c in of("sponsor")), ""),
                         responsible_party=next(iter(of("responsible_party")), None),
                         central=of("central"), officials=of("official"), page_url=page_url(nct_id))


async def _contact_rows(reader: SqlReader, nct_id: NctId) -> list[dict]:
    return await reader.fetch(
        f"SELECT kind, site_ordinal, name, role, email, phone, affiliation, title FROM {reader.table('trial_contact')} "
        "WHERE nct_id = $1 ORDER BY kind, site_ordinal, ordinal", (nct_id,))


def _contact(r: dict) -> Contact:
    return Contact(name=r["name"], role=r["role"], email=r["email"], phone=r["phone"], affiliation=r["affiliation"],
                   title=r["title"])


async def outcomes(reader: SqlReader, nct_id: NctId) -> Outcomes:
    flag = await reader.fetch(f"SELECT has_results FROM {reader.table('trial')} WHERE nct_id = $1", (nct_id,))
    rows = await reader.fetch(
        f"SELECT kind, ordinal, title, description, time_frame, type, unit, param_type "
        f"FROM {reader.table('trial_outcome')} WHERE nct_id = $1 ORDER BY kind, ordinal", (nct_id,))
    values: dict[int, list[ResultValue]] = {}
    for v in await reader.fetch(
            f"SELECT result_ordinal, group_title, label, value, spread, lower_limit, upper_limit "
            f"FROM {reader.table('trial_outcome_value')} WHERE nct_id = $1 ORDER BY result_ordinal, ordinal", (nct_id,)):
        values.setdefault(v["result_ordinal"], []).append(ResultValue(
            group=v["group_title"], value=v["value"], spread=v["spread"], lower=v["lower_limit"],
            upper=v["upper_limit"], label=v["label"]))
    publications = await reader.fetch(f"SELECT pmid, type, citation FROM {reader.table('trial_publication')} "
                                      "WHERE nct_id = $1 ORDER BY ordinal", (nct_id,))
    of = lambda kind: tuple(OutcomeMeasure(measure=r["title"], description=r["description"],  # noqa: E731
                                           time_frame=r["time_frame"]) for r in rows if r["kind"] == kind)
    return Outcomes(primary=of("primary"), secondary=of("secondary"), other=of("other"),
                    has_results=bool(flag and flag[0]["has_results"]),
                    results=tuple(PostedResult(type=r["type"], title=r["title"], description=r["description"],
                                               time_frame=r["time_frame"], unit=r["unit"], param_type=r["param_type"],
                                               values=tuple(values.get(r["ordinal"], ())))
                                  for r in rows if r["kind"] == "result"),
                    publications=tuple(Publication(pmid=r["pmid"], type=r["type"], citation=r["citation"])
                                       for r in publications))


# Trials, Criteria, Sites, contacts and Outcomes are NOT written here: app.worldmodel.timeline.record_trials (World Model ingest → projector).
