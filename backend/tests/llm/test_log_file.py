"""Seam: the operator's log file (#35). Every model call through llm.complete writes one JSON line, with the model
faked; a log file that cannot be written never fails the call."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from app import llm, logfile
from app.llm import Lane, LlmUnavailable
from app.llm.nightshift import FakeLLM


class Answer(BaseModel):
    answer: str


def lines(path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


@pytest.fixture
def log_path(tmp_path):
    path = tmp_path / "logs" / "trialmatch.jsonl"
    logfile.configure(path)
    yield path
    logfile.reset()


async def test_a_model_call_writes_one_line_with_lane_models_prompts_raw_reply_parsed_value_and_duration(log_path):
    fake = FakeLLM(lambda lane, system, user: {"answer": "yes"})

    await llm.complete(SimpleNamespace(llm=fake), Lane.FAST, system="You are terse.", user="Is it?", out=Answer,
                       run_id=None)

    [line] = [x for x in lines(log_path) if x["step"] == "llm.complete"]
    assert line["lane"] == "fast"
    assert line["model_requested"] == "fake" and line["model_answered"] == "fake"
    assert line["system"] == "You are terse." and line["user"] == "Is it?"
    assert json.loads(line["raw"]) == {"answer": "yes"}
    assert line["parsed"] == {"answer": "yes"} and line["error"] is None
    assert isinstance(line["duration_ms"], int) and line["run_id"] is None
    assert line["at"] and line["level"] == "INFO"


async def test_a_reply_that_does_not_parse_is_logged_with_its_error_on_each_attempt(log_path):
    fake = FakeLLM(lambda lane, system, user: {"answer": 1})

    with pytest.raises(LlmUnavailable):
        await llm.complete(SimpleNamespace(llm=fake), Lane.JUDGE, system="s", user="u", out=Answer, run_id=None)

    calls = [x for x in lines(log_path) if x["step"] == "llm.complete"]
    assert len(calls) == 2
    assert all(c["parsed"] is None and "validation error" in c["error"] for c in calls)
    assert "did not match the schema" in calls[1]["user"]


async def test_an_unavailable_model_is_logged_with_its_error(log_path):
    with pytest.raises(LlmUnavailable):
        await llm.complete(SimpleNamespace(llm=FakeLLM()), Lane.DEEP, system="s", user="u", out=Answer, run_id=None)

    [line] = [x for x in lines(log_path) if x["step"] == "llm.complete"]
    assert line["lane"] == "deep" and line["raw"] is None and "no response scripted" in line["error"]


async def test_a_log_file_that_cannot_be_written_never_fails_the_call(tmp_path):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("")
    logfile.configure(blocker / "trialmatch.jsonl")   # its directory is a file
    try:
        done = await llm.complete(SimpleNamespace(llm=FakeLLM(lambda *_: {"answer": "yes"})), Lane.FAST,
                                  system="s", user="u", out=Answer, run_id=None)
    finally:
        logfile.reset()
    assert done.value == Answer(answer="yes")
