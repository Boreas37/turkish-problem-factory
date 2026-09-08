from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from problem_factory.config import Settings
from problem_factory.errors import LLMError
from problem_factory.llm import LLMResponse
from problem_factory.pipeline import Pipeline
from problem_factory.prompt import SYSTEM_PROMPT
from problem_factory.source import discover_sources

ROOT = Path(__file__).parents[1]
BASE_RESPONSE = json.loads((ROOT / "examples/fake-responses/basic.json").read_text("utf-8"))[
    "results"
][0]


def test_prompt_requires_portable_cpp20_headers():
    assert "never use non-standard" in SYSTEM_PROMPT
    assert "<bits/stdc++.h>" in SYSTEM_PROMPT


class QueueAdapter:
    model = "muse-spark-1.3-contributor-free"
    effort = "xhigh"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def generate(self, system: str, prompt: str) -> LLMResponse:
        self.calls += 1
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return LLMResponse(json.dumps(value, ensure_ascii=False), f"req-{self.calls}")


def settings(tmp_path: Path, **overrides) -> Settings:
    values = {
        "root": tmp_path,
        "api_key": None,
        "base_url": "https://example.invalid/v1",
        "model": "muse-spark-1.3-contributor-free",
        "effort": "xhigh",
        "batch_size": 5,
        "max_retries": 0,
        "request_timeout_seconds": 10,
        "backoff_base_seconds": 0,
        "backoff_max_seconds": 0,
    }
    values.update(overrides)
    return Settings(**values)


def source_file(tmp_path: Path, count: int = 1) -> Path:
    original = json.loads((ROOT / "examples/sources/basic.json").read_text("utf-8"))
    base = original["problems"][0]
    original["problems"] = []
    for index in range(count):
        item = copy.deepcopy(base)
        item["id"] = f"sum-{index}"
        original["problems"].append(item)
    path = tmp_path / "source.json"
    path.write_text(json.dumps(original), "utf-8")
    return path


def result_for(index: int) -> dict:
    result = copy.deepcopy(BASE_RESPONSE)
    result["source_key"] = f"yerel-ornekler:sum-{index}"
    result["package"]["slug"] = f"toplam-{index}"
    return result


def test_completed_source_never_calls_llm_again(tmp_path: Path):
    adapter = QueueAdapter([{"results": [result_for(0)]}])
    pipeline = Pipeline(settings(tmp_path), adapter)
    first = pipeline.process(source_file(tmp_path))
    second = pipeline.process(tmp_path / "source.json")
    assert first["completed"] == 1
    assert second == {"discovered": 1, "completed": 0, "failed": 0, "skipped": 1}
    assert adapter.calls == 1


def test_bad_item_is_retried_without_losing_valid_item(tmp_path: Path):
    bad = result_for(1)
    del bad["package"]["time_limit_ms"]
    adapter = QueueAdapter(
        [
            {"results": [result_for(0), bad]},
            {"results": [result_for(1)]},
        ]
    )
    outcome = Pipeline(settings(tmp_path), adapter).process(source_file(tmp_path, 2))
    assert outcome["completed"] == 2
    assert outcome["failed"] == 0
    assert adapter.calls == 2
    assert len(list((tmp_path / "artifacts/completed").glob("*/problem.json"))) == 2


def test_file_fields_nested_in_package_are_normalized(tmp_path: Path):
    nested = result_for(0)
    for field in ("reference_solution", "test_generator", "test_strategy"):
        nested["package"][field] = nested.pop(field)
    adapter = QueueAdapter([{"results": [nested]}])

    outcome = Pipeline(settings(tmp_path), adapter).process(source_file(tmp_path))

    assert outcome["completed"] == 1
    completed = next((tmp_path / "artifacts/completed").iterdir())
    assert (completed / "reference.cpp").is_file()
    assert (completed / "generator.py").is_file()
    assert (completed / "test-strategy.md").is_file()


def test_invalid_generator_syntax_is_recorded_as_failed(tmp_path: Path):
    invalid = result_for(0)
    invalid["test_generator"] = "def broken(:\n"
    adapter = QueueAdapter([{"results": [invalid]}])

    outcome = Pipeline(settings(tmp_path), adapter).process(source_file(tmp_path))

    assert outcome["failed"] == 1
    row = Pipeline(settings(tmp_path), adapter).state.rows()[0]
    assert row["status"] == "failed"
    assert "generator syntax error" in row["last_error"]


def test_generated_sample_category_is_normalized(tmp_path: Path):
    response = result_for(0)
    response["test_generator"] = (
        'import json\nprint(json.dumps([{"input": "0 0\\n", "category": "sample"}]))\n'
    )
    adapter = QueueAdapter([{"results": [response]}])

    outcome = Pipeline(settings(tmp_path), adapter).process(source_file(tmp_path))

    assert outcome["completed"] == 1


def test_429_preserves_pending_state(tmp_path: Path):
    adapter = QueueAdapter([LLMError("quota", status_code=429, transient=True)])
    pipeline = Pipeline(settings(tmp_path), adapter)
    with pytest.raises(LLMError, match="quota"):
        pipeline.process(source_file(tmp_path))
    row = pipeline.state.rows()[0]
    assert row["status"] == "pending"
    assert row["attempt_count"] == 1


def test_transient_error_uses_backoff_then_succeeds(tmp_path: Path):
    adapter = QueueAdapter(
        [
            LLMError("temporary", status_code=503, transient=True),
            {"results": [result_for(0)]},
        ]
    )
    sleeps = []
    pipeline = Pipeline(
        settings(
            tmp_path,
            max_retries=1,
            backoff_base_seconds=0.25,
            backoff_max_seconds=1,
        ),
        adapter,
        sleeper=sleeps.append,
    )
    outcome = pipeline.process(source_file(tmp_path))
    assert outcome["completed"] == 1
    assert sleeps == [0.25]


def test_wholly_malformed_batch_falls_back_to_singletons(tmp_path: Path):
    adapter = QueueAdapter(
        [
            "not used",
            {"results": [result_for(0)]},
            {"results": [result_for(1)]},
        ]
    )
    adapter.responses[0] = {"wrong": []}
    outcome = Pipeline(settings(tmp_path), adapter).process(source_file(tmp_path, 2))
    assert outcome["completed"] == 2
    assert adapter.calls == 3


def test_changed_source_clears_old_artifact_pointer(tmp_path: Path):
    adapter = QueueAdapter([{"results": [result_for(0)]}])
    source = source_file(tmp_path)
    pipeline = Pipeline(settings(tmp_path), adapter)
    assert pipeline.process(source)["completed"] == 1
    document = json.loads(source.read_text("utf-8"))
    document["problems"][0]["statement"] += " Changed."
    source.write_text(json.dumps(document), "utf-8")
    pipeline.state.register(next(iter(discover_sources(source))))
    row = pipeline.state.rows()[0]
    assert row["status"] == "pending"
    assert row["artifact_path"] is None
