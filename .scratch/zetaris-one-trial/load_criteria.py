"""One-Trial test, step 3: read a Trial's eligibility text THROUGH ZETARIS, split it into Criteria, write Postgres.

  ctgov.ctgov_trial_core (Zetaris REST view)  →  split()  →  trial + criterion rows (our Postgres, port 5433)

Test shortcut: this writes Postgres directly. ADR 0001 says the World Model engine is the only writer of these tables,
but worldmodel.timeline.record_trials is not implemented yet. Replace this with that call once it exists.

Splitting reuses ctgov-discovery/scripts/04_mine_terms.split, the rule criteria.split_deterministic will implement.
Text is stored as returned (markdown escapes kept), so criterion text matches what Zetaris holds.

Usage (asyncpg lives in the backend venv; ZETARIS_API_KEY comes from .env.local):
  backend/.venv/bin/python .scratch/zetaris-one-trial/load_criteria.py [NCT07680790]
"""
from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DISCOVERY = HERE.parent / "ctgov-discovery"
sys.path[:0] = [str(DISCOVERY / "ref"), str(DISCOVERY / "scripts")]

import asyncpg  # noqa: E402
import zetaris_sql as z  # noqa: E402

_spec = importlib.util.spec_from_file_location("mine", DISCOVERY / "scripts" / "04_mine_terms.py")
mine = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mine)

PG_DSN = os.environ.get("TRIALMATCH_PG_DSN", "postgresql://trialmatch:trialmatch@localhost:5433/trialmatch")


def eligibility_hash(text: str) -> str:
    """sha256 over whitespace-normalised text (the rule in backend/app/trials/ctgov.py)."""
    return hashlib.sha256(re.sub(r"\s+", " ", text).strip().encode()).hexdigest()


def read_from_zetaris(nct: str) -> tuple[str, str, list[str], str, str]:
    """→ (nct_id, title, conditions, status, eligibility_text) from the Zetaris view."""
    if not re.fullmatch(r"NCT\d{8}", nct):   # inlined into SQL: the REST API has no bind params
        raise SystemExit(f"not an NCT ID: {nct!r}")
    z.load_env(None) or z.load_env(str(HERE.parents[1] / ".env"))   # .env.local first, then the repo's .env
    ch = z.open_channel("rest")
    try:
        rows = ch.run(
            "SELECT nct_id, title, conditions, overall_status, eligibility_text FROM ctgov.ctgov_trial_core "
            f"WHERE nct_id = '{nct}'"
        ).rows
    finally:
        ch.close()
    if len(rows) != 1:
        raise SystemExit(f"expected 1 row for {nct} in ctgov.ctgov_trial_core, got {len(rows)}")
    nct_id, title, conditions, status, text = rows[0]
    return nct_id, title, conditions.split("|") if conditions else [], status, text


async def write_postgres(nct: str, title: str, conditions: list[str], status: str, text: str) -> int:
    h = eligibility_hash(text)
    items, clean = mine.split(text)
    if not clean:
        print(f"warning: split not clean for {nct} (missing heading or empty section)")
    conn = await asyncpg.connect(PG_DSN)
    try:
        async with conn.transaction():
            await conn.execute(
                """INSERT INTO trial (nct_id, title, conditions, status, eligibility_text, eligibility_hash, source, fetched_at)
                   VALUES ($1, $2, $3, $4, $5, $6, 'zetaris', now())
                   ON CONFLICT (nct_id) DO UPDATE SET title = $2, status = $4, eligibility_text = $5,
                     eligibility_hash = $6, source = 'zetaris', fetched_at = now()""",
                nct, title, conditions, status, text, h,
            )
            # Criteria are immutable per (nct, hash): re-running with the same text inserts nothing new.
            for ordinal, (kind, item) in enumerate(items, 1):
                await conn.execute(
                    """INSERT INTO criterion (id, nct_id, eligibility_hash, kind, ordinal, text)
                       VALUES ($1, $2, $3, $4, $5, $6) ON CONFLICT (id) DO NOTHING""",
                    f"{nct}:{h[:8]}:{ordinal}", nct, h, kind, ordinal, item,
                )
    finally:
        await conn.close()
    return len(items)


def main(nct: str) -> None:
    nct, title, conditions, status, text = read_from_zetaris(nct)
    n = asyncio.run(write_postgres(nct, title, conditions, status, text))
    print(f"{nct}: {n} Criteria written, eligibility_hash {eligibility_hash(text)[:8]}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "NCT07680790")
