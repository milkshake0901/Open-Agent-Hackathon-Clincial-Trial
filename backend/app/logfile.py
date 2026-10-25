"""app/logfile.py — the operator's log file (#35): one JSON object per line, rotated by size.

`configure(path)` is called once per process (app lifespan, scripts/ingest_trials.py); it puts a JSON-lines
handler on the `app` logger, so any module's `logging.getLogger(__name__)` lands in the file. A pipeline step is
written with `step(log, "matching.rescan.started", field=...)`: the line carries `step` and the fields at top
level. Writing the log never fails the work it describes: a bad path or a full disk is reported on stderr by
logging itself, and `step` swallows its own errors.

Only what the model already sees, or ids, goes in a line: never Search preferences, names or contact details."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

ROOT_LOGGER = "app"
_handler: logging.Handler | None = None


class JsonLines(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        line: dict[str, Any] = {
            "at": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname, "logger": record.name,
            "step": getattr(record, "step", None), "message": record.getMessage(),
        }
        line.update(getattr(record, "fields", None) or {})
        if record.exc_info:
            line["exception"] = self.formatException(record.exc_info)
        return json.dumps(line, default=str, ensure_ascii=False)


def configure(path: str | Path, *, max_bytes: int = 10_000_000, backups: int = 5) -> None:
    """Send the `app` loggers (INFO and up) to `path` as JSON lines. Calling it again moves the file."""
    global _handler
    reset()
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass   # the handler opens lazily; logging reports the failure on the first line instead
    handler = RotatingFileHandler(path, maxBytes=max_bytes, backupCount=backups, encoding="utf-8", delay=True)
    handler.setFormatter(JsonLines())
    logger = logging.getLogger(ROOT_LOGGER)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    _handler = handler


def reset() -> None:
    """Remove the handler `configure` installed (tests)."""
    global _handler
    if _handler is not None:
        logging.getLogger(ROOT_LOGGER).removeHandler(_handler)
        _handler.close()
        _handler = None


def step(log: logging.Logger, name: str, **fields: Any) -> None:
    """One line for a pipeline step. Never raises."""
    try:
        log.info(name, extra={"step": name, "fields": fields})
    except Exception:   # noqa: BLE001 — the log must never fail the request
        pass
