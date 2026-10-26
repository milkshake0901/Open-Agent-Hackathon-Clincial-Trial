"""One-off (#53): de-identify the letters stored before the letter path de-identified them.

A letter is a Document with parsed Regions. Its Region text, page text, filename and patient label go through the same
de-identification as an upload today, in one pass per Document, and are updated in place. Boxes are not touched.
Running it again changes nothing more. It prints only counts, never text.

    doppler run -- backend/.venv/bin/python backend/scripts/deidentify_letters.py --dry-run
    doppler run -- backend/.venv/bin/python backend/scripts/deidentify_letters.py
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import asyncpg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings  # noqa: E402
from app.record.deidentify import deidentify_document  # noqa: E402
from app.record.types import Page  # noqa: E402

LETTERS = ("SELECT d.hash, d.filename, d.patient_id, p.label FROM document d JOIN patient p ON p.id = d.patient_id "
           "WHERE EXISTS (SELECT 1 FROM document_span s WHERE s.document_hash = d.hash) ORDER BY d.uploaded_at, d.hash")


def _tables(raw) -> tuple:
    value = json.loads(raw) if isinstance(raw, str) else (raw or [])
    return tuple(tuple(tuple(str(c) for c in row) for row in table) for table in value)


async def deidentify_letters(conn: asyncpg.Connection, *, dry_run: bool) -> dict[str, int]:
    counts = {"letters": 0, "regions": 0, "pages": 0, "filenames": 0, "labels": 0}
    labels: dict[str, str] = {}
    for letter in await conn.fetch(LETTERS):
        counts["letters"] += 1
        page_rows = await conn.fetch("SELECT number, text, tables_json FROM document_page WHERE document_hash = $1 "
                                     "ORDER BY number", letter["hash"])
        span_rows = await conn.fetch("SELECT id, text FROM document_span WHERE document_hash = $1 "
                                     "ORDER BY page, ordinal", letter["hash"])
        pages = tuple(Page(number=r["number"], text=r["text"], tables=_tables(r["tables_json"])) for r in page_rows)
        regions = tuple(r["text"] for r in span_rows)
        done = deidentify_document(pages, regions, filename=letter["filename"])
        label = labels.get(letter["patient_id"], letter["label"])
        labels[letter["patient_id"]] = deidentify_document(pages, regions, filename=label).filename

        for row, text in zip(span_rows, done.regions):
            if text != row["text"]:
                counts["regions"] += 1
                if not dry_run:
                    await conn.execute("UPDATE document_span SET text = $1 WHERE id = $2", text, row["id"])
        for old, new in zip(pages, done.pages):
            if new != old:
                counts["pages"] += 1
                if not dry_run:
                    await conn.execute("UPDATE document_page SET text = $1, tables_json = $2::jsonb "
                                       "WHERE document_hash = $3 AND number = $4",
                                       new.text, json.dumps(new.tables), letter["hash"], new.number)
        if done.filename != letter["filename"]:
            counts["filenames"] += 1
            if not dry_run:
                await conn.execute("UPDATE document SET filename = $1 WHERE hash = $2", done.filename, letter["hash"])

    originals = {r["id"]: r["label"] for r in await conn.fetch(
        "SELECT id, label FROM patient WHERE id = ANY($1::text[])", list(labels))}
    for patient_id, label in labels.items():
        if label != originals[patient_id]:
            counts["labels"] += 1
            if not dry_run:
                await conn.execute("UPDATE patient SET label = $1 WHERE id = $2", label, patient_id)
    return counts


async def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="deidentify_letters.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="count what would change; write nothing")
    args = parser.parse_args(argv)
    conn = await asyncpg.connect(Settings().pg_dsn)
    try:
        async with conn.transaction():
            counts = await deidentify_letters(conn, dry_run=args.dry_run)
    finally:
        await conn.close()
    for name, count in counts.items():
        print(f"{name} {count}")
    if args.dry_run:
        print("dry run: nothing was written")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
