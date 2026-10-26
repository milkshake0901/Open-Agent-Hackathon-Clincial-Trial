"""Parse a scanned referral and store each region so a trial reason can cite the box on the page.

    doppler run -- backend/.venv/bin/python scripts/load_referral.py path/to/file.pdf
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import asyncpg

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.config import REPO_ROOT, Settings  # noqa: E402
from app.extraction.parse import extract_pdf  # noqa: E402
from app.record.referral import save_referral  # noqa: E402
from app.record.storage import keep_raw  # noqa: E402
from app.sql.writer import PgWriter  # noqa: E402

PATIENT_ID = "pt_referral_20260209"
LABEL = "Referral 09 Feb 2026"


async def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: load_referral.py FILE.pdf", file=sys.stderr)
        return 2
    path = Path(argv[0])
    content = path.read_bytes()
    parsed = extract_pdf(content)
    settings = Settings()
    pool = await asyncpg.create_pool(settings.pg_dsn, min_size=1, max_size=2)
    try:
        digest = await save_referral(
            PgWriter(pool), patient_id=PATIENT_ID, label=LABEL, filename_raw=path.name,
            content=content, parsed=parsed)
        keep_raw(str(REPO_ROOT / settings.raw_documents_dir), digest, content)
        rows = await pool.fetch(
            "SELECT id, page, kind, y0, text FROM document_span WHERE document_hash = $1 ORDER BY page, ordinal",
            digest)
    finally:
        await pool.close()
    print(f"document {digest}")
    print(f"spans {len(rows)}")
    for row in rows:
        if row["kind"] == "Page-header" or row["text"].startswith("OC."):
            print(f"  header {row['id']} p{row['page']} y={row['y0']:.3f} {row['text']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
