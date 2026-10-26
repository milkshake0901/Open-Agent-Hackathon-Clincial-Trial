"""The one-off script de-identifies letters stored before #53, in place, against the test database only.

A letter is seeded the way the old letter path stored it: Region text, page text, filename and patient label as read.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys

from app.record.repo import insert_document, insert_spans
from app.record.storage import document_hash
from app.record.types import Document, Page, PatientId
from app.sql.writer import PgWriter
from tests.api.test_letter_deidentification_api import CONTENT, FILENAME, PAGES, assert_no_identifier
from tests.conftest import ADMIN_DSN, NOW, _with_db
from tests.test_scripts import BACKEND, SCRIPTS

PATIENT = "pt_old_letter"
COUNTS = re.compile(r"(letters|regions|pages|filenames|labels) \d+|dry run: nothing was written")


async def seed_letter_as_stored_before_the_fix(pool) -> None:
    digest = document_hash(PatientId(PATIENT), CONTENT)
    pages = tuple(Page(number=n, text="\n".join(text for _, text, _ in regions)) for n, regions in PAGES)
    spans = [(f"{digest[:12]}:p{n}:b{i}", n, i, kind, text, *box)
             for n, regions in PAGES for i, (kind, text, box) in enumerate(regions)]
    async with PgWriter(pool).transaction() as tx:
        await tx.execute("INSERT INTO patient (id, label) VALUES ($1, $2)", (PATIENT, FILENAME))
        await insert_document(tx, Document(hash=digest, patient_id=PatientId(PATIENT), filename=FILENAME, pages=pages,
                                           uploaded_at=NOW.date()), uploaded_at=NOW)
        await insert_spans(tx, digest, spans)


async def stored(pool) -> list[tuple]:
    rows = [*await pool.fetch("SELECT id, kind, text, x0, y0, x1, y1 FROM document_span ORDER BY id"),
            *await pool.fetch("SELECT document_hash, number, text FROM document_page ORDER BY number"),
            *await pool.fetch("SELECT hash, filename FROM document"),
            *await pool.fetch("SELECT id, label FROM patient")]
    return [tuple(r.values()) for r in rows]


def run_script(pool_dsn: str, *args: str) -> subprocess.CompletedProcess[str]:
    done = subprocess.run([sys.executable, str(SCRIPTS / "deidentify_letters.py"), *args], cwd=BACKEND,
                          env={**os.environ, "PG_DSN": pool_dsn}, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    assert done.stderr == ""
    return done


async def test_the_script_de_identifies_stored_letters_once_and_its_dry_run_prints_only_counts(clean_db):
    await seed_letter_as_stored_before_the_fix(clean_db)
    dsn = _with_db(ADMIN_DSN, await clean_db.fetchval("SELECT current_database()"))
    before = await stored(clean_db)

    dry = run_script(dsn, "--dry-run")
    assert all(COUNTS.fullmatch(line) for line in dry.stdout.splitlines()), dry.stdout
    assert dry.stdout.splitlines()[:5] == ["letters 1", "regions 8", "pages 2", "filenames 1", "labels 1"]
    assert await stored(clean_db) == before

    first = run_script(dsn)
    assert first.stdout.splitlines() == [line for line in dry.stdout.splitlines() if not line.startswith("dry run")]
    after = await stored(clean_db)
    for row in after:
        assert_no_identifier(str(row))
    assert [r[3:] for r in after if len(r) == 7] == [r[3:] for r in before if len(r) == 7]  # every box kept

    again = run_script(dsn)
    assert again.stdout.splitlines() == ["letters 1", "regions 0", "pages 0", "filenames 0", "labels 0"]
    assert await stored(clean_db) == after
