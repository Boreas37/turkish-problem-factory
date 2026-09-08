from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from problem_factory.judge0 import (
    ExecutionResult,
    Judge0Adapter,
    Judge0Error,
    Judge0Settings,
    smoke_package,
)

ROOT = Path(__file__).parents[1]
PACKAGE = ROOT / "examples/generated/iki-sayinin-toplami-1b4cb76cf359"


class FakeJudge0:
    def __init__(self, *, fail: bool = False):
        self.fail = fail
        self.calls = 0

    def execute(self, source: str, stdin: str, problem: dict) -> ExecutionResult:
        self.calls += 1
        if self.fail:
            return ExecutionResult(6, "Compilation Error", "", None, "bad compile", None, None)
        left, right = map(int, stdin.split())
        return ExecutionResult(3, "Accepted", f"{left + right}  \n", None, None, "0.001", 1024)


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    for file in sorted(item for item in path.rglob("*") if item.is_file()):
        digest.update(str(file.relative_to(path)).encode())
        digest.update(file.read_bytes())
    return digest.hexdigest()


def test_optional_judge0_adapter_can_be_mocked():
    adapter = FakeJudge0()
    result = smoke_package(PACKAGE, adapter, max_tests=3)
    assert result["compatible"] is True
    assert result["tests_run"] == 3
    assert adapter.calls == 3


def test_judge0_failure_does_not_modify_completed_package():
    before = _digest(PACKAGE)
    with pytest.raises(Judge0Error, match="Compilation Error"):
        smoke_package(PACKAGE, FakeJudge0(fail=True), max_tests=1)
    assert _digest(PACKAGE) == before


class FakeHTTPResponse:
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, *_args):
        return json.dumps(self.value).encode()


def test_judge0_language_id_is_central_adapter_configuration(monkeypatch):
    requests = []
    responses = iter(
        [
            {"token": "token-1"},
            {
                "status": {"id": 3, "description": "Accepted"},
                "stdout": "3\n",
                "time": "0.001",
                "memory": 1024,
            },
        ]
    )

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return FakeHTTPResponse(next(responses))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    adapter = Judge0Adapter(
        Judge0Settings("http://judge0.local", "token", 105), sleeper=lambda _delay: None
    )
    problem = json.loads((PACKAGE / "problem.json").read_text("utf-8"))
    result = adapter.execute("int main(){}", "1 2\n", problem)
    payload = json.loads(requests[0][0].data)
    assert payload["language_id"] == 105
    assert "compiler_options" not in payload
    assert requests[0][0].get_header("X-auth-token") == "token"
    assert result.status_id == 3
