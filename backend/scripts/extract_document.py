"""Read a scanned PDF with Nemotron Parse.

    doppler run -- backend/.venv/bin/python backend/scripts/extract_document.py path/to/file.pdf
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings  # noqa: E402
from app.extraction import NemotronParse  # noqa: E402


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: extract_document.py FILE.pdf", file=sys.stderr)
        return 2
    path = Path(argv[0])
    document = NemotronParse(Settings()).read(path.read_bytes())
    print(document.text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
