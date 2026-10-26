"""Shared test harness.

Facade tests run against a throwaway Postgres database built from THIS worktree's db/schema.sql,
with the World Model on PgEventStore so the projector fills the tables the record reads. (Spec #5
says "in-memory event store"; that leaves every SQL read empty, so facade tests use Postgres.)
The shared `trialmatch` database is never written: tests only connect to it to CREATE/DROP their own.

Override the admin DSN with TRIALMATCH_TEST_PG_DSN. DB tests are skipped if the server is unreachable.
"""
import os
import re
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

SCHEMA = Path(__file__).resolve().parents[2] / "db" / "schema.sql"
ADMIN_DSN = os.environ.get("TRIALMATCH_TEST_PG_DSN", "postgresql://trialmatch:trialmatch@localhost:5433/trialmatch")
NOW = datetime(2026, 10, 24, 9, 30, tzinfo=UTC)


def _db_name() -> str:
    worktree = re.sub(r"[^a-z0-9]+", "_", Path(__file__).resolve().parents[2].name.lower()).strip("_")
    return f"tm_test_{worktree[:30]}_{uuid.uuid4().hex[:8]}"


def _with_db(dsn: str, name: str) -> str:
    return dsn.rsplit("/", 1)[0] + "/" + name


@pytest.fixture(scope="session")
async def pg_pool():
    asyncpg = pytest.importorskip("asyncpg")
    try:
        admin = await asyncpg.connect(ADMIN_DSN, timeout=3)
    except (OSError, asyncpg.PostgresError) as e:
        pytest.skip(f"Postgres unreachable at {ADMIN_DSN}: {e}")
    name = _db_name()
    await admin.execute(f'CREATE DATABASE "{name}"')
    try:
        conn = await asyncpg.connect(_with_db(ADMIN_DSN, name))
        await conn.execute(SCHEMA.read_text())
        await conn.close()
        pool = await asyncpg.create_pool(_with_db(ADMIN_DSN, name), min_size=1, max_size=4)
        try:
            yield pool
        finally:
            await pool.close()
    finally:
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await admin.close()


@pytest.fixture
async def clean_db(pg_pool):
    tables = [r["tablename"] for r in await pg_pool.fetch("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")]
    await pg_pool.execute(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE")
    return pg_pool


def make_ctx(pool, llm=None, parser=None):
    """A test Ctx: Postgres writer and readers, fake model, recorded parse, World Model on PgEventStore, fixed clock."""
    from app.config import Settings
    from app.ctx import Ctx
    from app.llm.nightshift import FakeLLM
    from app.sql.reader import PgReader
    from app.sql.writer import PgWriter
    from app.worldmodel import PgEventStore, WorldModel
    from tests.fixtures.letters import RecordedParse

    writer = PgWriter(pool)
    reader = PgReader(pool)
    wm = WorldModel(namespace="test", store=PgEventStore(writer, "test"), clock=lambda: NOW)
    return Ctx(writer=writer, agent_reader=reader, ui_reader=reader, llm=llm or FakeLLM(),
               parser=parser or RecordedParse(), wm=wm,
               settings=Settings(_env_file=None, pg_dsn=ADMIN_DSN), now=lambda: NOW)


class Recording:
    """A Postgres agent reader (Zetaris in production) noting every table read through it, to check what a model
    call is given was read through the agent path (ADR 0001)."""

    def __init__(self, pool):
        from app.sql.reader import PgReader
        self._reader = PgReader(pool)
        self.tables: set[str] = set()
        self.fetch, self.wait_visible = self._reader.fetch, self._reader.wait_visible

    def table(self, name: str) -> str:
        self.tables.add(name)
        return self._reader.table(name)


@pytest.fixture
def fake_llm():
    from app.llm.nightshift import FakeLLM
    return FakeLLM()


@pytest.fixture
def ctx(clean_db, fake_llm):
    return make_ctx(clean_db, fake_llm)
