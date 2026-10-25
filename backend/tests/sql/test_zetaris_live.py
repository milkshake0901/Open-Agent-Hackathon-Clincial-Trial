"""The same repo query functions through ZetarisReader and PgReader, against the shared `trialmatch` database and the
local Zetaris it is registered in (ADR 0001): each must give the same domain objects. Read-only.

Skipped unless ZETARIS_API_KEY is set (the repo's .env) and both Postgres and Zetaris answer. After a migration that
adds a table or column, run REGISTER DATASOURCE TABLES FROM trialmatch first (db/zetaris_register.sql).
"""
from __future__ import annotations

import asyncpg
import httpx
import pytest

from app.config import Settings
from app.matching import repo as matching_repo
from app.record import repo as record_repo
from app.sql.reader import PgReader, ZetarisError, ZetarisReader, pg_column_types
from app.trials import NctId, repo as trials_repo

S = Settings()
pytestmark = pytest.mark.skipif(not S.zetaris_api_key, reason="ZETARIS_API_KEY not set")


@pytest.fixture
async def readers():
    try:
        pool = await asyncpg.create_pool(S.pg_dsn, min_size=1, max_size=2)
    except (OSError, asyncpg.PostgresError) as e:
        pytest.skip(f"shared Postgres unreachable: {e}")
    http = httpx.AsyncClient()
    zetaris = ZetarisReader(S.zetaris_rest_url, S.zetaris_api_key, S.zetaris_org_id, S.zetaris_datasource, http,
                            await pg_column_types(pool))
    try:
        await zetaris.fetch(f"SELECT 1 AS one FROM {zetaris.table('trial')} LIMIT 1")
    except ZetarisError as e:
        await http.aclose(), await pool.close()
        pytest.skip(f"Zetaris unavailable: {e}")
    yield PgReader(pool), zetaris
    await http.aclose()
    await pool.close()


async def both(readers, fn, *args, **kw):
    pg, zetaris = readers
    return await fn(pg, *args, **kw), await fn(zetaris, *args, **kw)


async def sample(pg: PgReader, sql: str) -> list:
    return [next(iter(r.values())) for r in await pg.fetch(sql)]


async def test_trials_their_sites_contacts_criteria_and_outcomes_read_the_same_through_zetaris(readers):
    pg, _ = readers
    ncts = await sample(pg, "SELECT nct_id FROM trial WHERE NOT dropped ORDER BY has_results DESC, nct_id LIMIT 3")
    ncts += await sample(pg, "SELECT DISTINCT nct_id FROM criterion")   # one with split Criteria
    ncts += await sample(pg, "SELECT nct_id FROM trial WHERE title LIKE '%''%' OR title LIKE '%\\%' LIMIT 2")
    for nct in map(NctId, ncts):
        via_pg, via_zetaris = await both(readers, trials_repo.trial, nct)
        assert via_zetaris == via_pg, nct
        for fn in (trials_repo.sites, trials_repo.contacts, trials_repo.outcomes):
            a, b = await both(readers, fn, nct)
            assert b == a, (fn.__name__, nct)
        a, b = await both(readers, trials_repo.criteria, nct, via_pg.eligibility_hash)
        assert b == a, nct


async def test_the_open_trial_list_reads_the_same_through_zetaris(readers):
    via_pg, via_zetaris = await both(readers, trials_repo.active_trials)
    assert len(via_zetaris) == len(via_pg) > 0
    assert via_zetaris == via_pg


async def test_profile_versions_and_verdicts_read_the_same_through_zetaris(readers):
    pg, _ = readers
    versions = await sample(pg, "SELECT id FROM profile_version ORDER BY id")
    if not versions:
        pytest.skip("no Profile versions in the shared database")
    for vid in versions:
        a, b = await both(readers, record_repo.version, vid, with_facts=True)
        assert b == a, vid
        a, b = await both(readers, matching_repo.trials_needing_verdict, vid, None)
        assert b == a, vid
        for nct in await sample(pg, f"SELECT nct_id FROM verdict WHERE profile_version_id = '{vid}'"):
            a, b = await both(readers, matching_repo.verdict, NctId(nct), vid, with_results=True)
            assert b == a, (vid, nct)
    for pid in await sample(pg, "SELECT id FROM patient"):
        a, b = await both(readers, record_repo.current_version, pid)
        assert b == a, pid
