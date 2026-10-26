"""app/ctx.py — the one dependency bundle every facade takes.

Writers: the World Model (domain tables, via its projector), record.repo (documents and
pages), app.trace (trace events and model calls). One owner per table. Two readers exist because of
ADR 0001: agents read through Zetaris, the HTTP shell reads Postgres directly.
Both readers implement SqlReader and run the SAME query functions in each
module's repo.py, so a question about the data has one SQL text.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from app.config import Settings
from app.extraction import Parser
from app.llm import LLM
from app.sql.reader import SqlReader
from app.sql.writer import PgWriter
from app.worldmodel import WorldModel


@dataclass(frozen=True)
class Ctx:
    writer: PgWriter
    agent_reader: SqlReader   # ZetarisReader in prod; PgReader in tests
    ui_reader: SqlReader      # PgReader
    llm: LLM                  # Nightshift in prod; FakeLLM in tests
    parser: Parser            # Nemotron Parse in prod; RecordedParse (tests/fixtures/letters.py) in tests
    wm: WorldModel            # Meterless World Model; PgEventStore in prod, InMemoryEventStore in tests.
                              # The only writer of facts, profile versions, trials and verdicts (ADR 0001).
    settings: Settings        # loop bounds, concurrency, lane models (config.py is the one place)
    now: Callable[[], datetime]
