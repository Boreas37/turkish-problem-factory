from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .errors import ConfigurationError, FactoryError
from .schema import load_and_validate
from .validation import normalized, validate_package


class Judge0Error(FactoryError):
    pass


@dataclass(frozen=True)
class Judge0Settings:
    url: str
    auth_token: str | None
    cpp20_language_id: int
    timeout_seconds: int = 30
    poll_interval_seconds: float = 0.5
    max_polls: int = 60

    @classmethod
    def from_env(cls) -> Judge0Settings:
        url = os.getenv("JUDGE0_URL")
        language_id = os.getenv("JUDGE0_CPP20_LANGUAGE_ID")
        if not url:
            raise ConfigurationError("JUDGE0_URL is required for judge0-smoke")
        if not language_id:
            raise ConfigurationError(
                "JUDGE0_CPP20_LANGUAGE_ID is required; IDs are installation-specific"
            )
        try:
            parsed_id = int(language_id)
        except ValueError as exc:
            raise ConfigurationError("JUDGE0_CPP20_LANGUAGE_ID must be an integer") from exc
        return cls(url.rstrip("/"), os.getenv("JUDGE0_AUTH_TOKEN"), parsed_id)


@dataclass(frozen=True)
class ExecutionResult:
    status_id: int
    status: str
    stdout: str
    stderr: str | None
    compile_output: str | None
    time: str | None
    memory: int | None


class ExecutionAdapter(Protocol):
    def execute(self, source: str, stdin: str, problem: dict) -> ExecutionResult: ...


class Judge0Adapter:
    def __init__(self, settings: Judge0Settings, *, sleeper=time.sleep):
        self.settings = settings
        self.sleeper = sleeper

    def _request(self, request: urllib.request.Request) -> dict[str, Any]:
        try:
            with urllib.request.urlopen(request, timeout=self.settings.timeout_seconds) as response:
                raw = response.read(4 * 1024 * 1024 + 1)
                if len(raw) > 4 * 1024 * 1024:
                    raise Judge0Error("Judge0 response exceeded 4 MiB")
                value = json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read(2048).decode("utf-8", "replace")
            raise Judge0Error(f"Judge0 HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, UnicodeError, json.JSONDecodeError) as exc:
            raise Judge0Error(f"Judge0 request failed: {exc}") from exc
        if not isinstance(value, dict):
            raise Judge0Error("Judge0 returned a non-object response")
        return value

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.settings.auth_token:
            headers["X-Auth-Token"] = self.settings.auth_token
        return headers

    def execute(self, source: str, stdin: str, problem: dict) -> ExecutionResult:
        payload = {
            "source_code": source,
            "language_id": self.settings.cpp20_language_id,
            "stdin": stdin,
            "cpu_time_limit": problem["time_limit_ms"] / 1000,
            "wall_time_limit": problem["wall_time_limit_ms"] / 1000,
            "memory_limit": problem["memory_limit_kb"],
            "max_file_size": problem["output_limit_kb"],
        }
        request = urllib.request.Request(
            f"{self.settings.url}/submissions?base64_encoded=false&wait=false",
            data=json.dumps(payload).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )
        created = self._request(request)
        token = created.get("token")
        if not isinstance(token, str):
            raise Judge0Error("Judge0 submission response did not contain a token")
        result: dict[str, Any] | None = None
        for _poll in range(self.settings.max_polls):
            query = urllib.request.Request(
                f"{self.settings.url}/submissions/{token}?base64_encoded=false",
                headers=self._headers(),
            )
            result = self._request(query)
            status = result.get("status") or {}
            if isinstance(status, dict) and isinstance(status.get("id"), int) and status["id"] > 2:
                break
            self.sleeper(self.settings.poll_interval_seconds)
        else:
            raise Judge0Error("Judge0 submission did not finish before the polling limit")
        status = result.get("status") or {}
        return ExecutionResult(
            status_id=status.get("id", 0),
            status=str(status.get("description", "unknown")),
            stdout=result.get("stdout") or "",
            stderr=result.get("stderr"),
            compile_output=result.get("compile_output"),
            time=result.get("time"),
            memory=result.get("memory"),
        )


def _inside(package: Path, relative: str) -> Path:
    candidate = (package / relative).resolve()
    if package != candidate and package not in candidate.parents:
        raise Judge0Error(f"test path escapes package: {relative}")
    return candidate


def smoke_package(path: Path, adapter: ExecutionAdapter, *, max_tests: int = 3) -> dict:
    if max_tests < 1:
        raise ValueError("max_tests must be at least 1")
    package = path.resolve()
    validate_package(package)
    problem = load_and_validate(package / "problem.json", "problem-v1.json")
    source = (package / "reference.cpp").read_text("utf-8")
    selected: list[dict] = []
    for test in problem["tests"]:
        if not selected or test["category"] in {"edge", "boundary", "adversarial", "stress"}:
            selected.append(test)
        if len(selected) >= max_tests:
            break
    selected_ids = {test["id"] for test in selected}
    for test in problem["tests"]:
        if len(selected) >= max_tests:
            break
        if test["id"] not in selected_ids:
            selected.append(test)
            selected_ids.add(test["id"])
    results = []
    for test in selected:
        stdin = _inside(package, test["input_file"]).read_text("utf-8")
        expected = _inside(package, test["output_file"]).read_text("utf-8")
        execution = adapter.execute(source, stdin, problem)
        if execution.status_id != 3:
            raise Judge0Error(
                f"{test['id']} failed with {execution.status}: "
                f"{execution.compile_output or execution.stderr or ''}"
            )
        if normalized(execution.stdout) != normalized(expected):
            raise Judge0Error(f"{test['id']} output differs under normalized_exact")
        results.append(
            {
                "id": test["id"],
                "status": execution.status,
                "time": execution.time,
                "memory": execution.memory,
            }
        )
    return {"compatible": True, "tests_run": len(results), "results": results}
