from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import time
from collections.abc import Callable
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import IO

from . import __version__
from .config import Settings
from .errors import LLMError, PackageValidationError
from .llm import LLMAdapter, LLMResponse
from .migration import migrate_package
from .prompt import SYSTEM_PROMPT, build_prompt, parse_response
from .source import SourceProblem, discover_sources
from .state import StateStore
from .validation import validate_package, validate_package_json


class Pipeline:
    def __init__(
        self,
        settings: Settings,
        adapter: LLMAdapter,
        *,
        sleeper: Callable[[float], None] = time.sleep,
    ):
        if adapter.effort != "xhigh":
            raise ValueError("adapter effort must be xhigh")
        self.settings, self.adapter, self.sleeper = settings, adapter, sleeper
        self.state = StateStore(settings.state_path)
        for name in ("raw", "processing", "completed", "failed"):
            (settings.artifacts_path / name).mkdir(parents=True, exist_ok=True)

    def process(self, source_path: Path, *, retry_failed: bool = False) -> dict[str, int]:
        with self._exclusive_run():
            return self._process_locked(source_path, retry_failed=retry_failed)

    def _process_locked(self, source_path: Path, *, retry_failed: bool) -> dict[str, int]:
        self.state.recover_processing()
        items = list(discover_sources(source_path))
        keys = [item.key for item in items]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate source id/name combination in input")
        if retry_failed:
            self.state.reset_failed(keys)
        self._snapshot_raw_sources(items)
        pending: list[SourceProblem] = []
        skipped = 0
        preflight_failed = 0
        for item in items:
            status = self.state.register(item)
            if status == "completed":
                try:
                    self._ensure_completed_current(item)
                    skipped += 1
                except (OSError, UnicodeError, ValueError, PackageValidationError) as exc:
                    self._fail(item, f"Completed artifact preflight failed: {exc}")
                    preflight_failed += 1
                continue
            if self._recover_completed_artifact(item):
                skipped += 1
                continue
            if status == "failed" and not retry_failed:
                continue
            pending.append(item)
        completed, failed = 0, preflight_failed
        for offset in range(0, len(pending), self.settings.batch_size):
            batch = pending[offset : offset + self.settings.batch_size]
            result = self._process_batch(batch, allow_split=True)
            completed += result[0]
            failed += result[1]
        return {
            "discovered": len(items),
            "completed": completed,
            "failed": failed,
            "skipped": skipped,
        }

    def _ensure_completed_current(self, item: SourceProblem) -> None:
        artifact = self.state.artifact_for(item)
        if artifact is None or not artifact.is_dir():
            raise PackageValidationError(["completed artifact directory is missing"])
        try:
            problem = json.loads((artifact / "problem.json").read_text("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise PackageValidationError([f"completed problem.json is unreadable: {exc}"]) from exc
        if problem.get("schema_version") == "1.0":
            migrate_package(artifact)
        elif problem.get("schema_version") != "1.1":
            raise PackageValidationError(
                [f"unsupported completed schema_version: {problem.get('schema_version')}"]
            )

    @contextmanager
    def _exclusive_run(self):
        lock_path = self.settings.root / "state.db.lock"
        lock_file: IO[str] = lock_path.open("a+", encoding="utf-8")
        try:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError(
                    f"another pipeline is already running for {self.settings.root}"
                ) from exc
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            lock_file.close()

    def _snapshot_raw_sources(self, items: list[SourceProblem]) -> None:
        seen: set[Path] = set()
        for item in items:
            if item.source_file in seen:
                continue
            seen.add(item.source_file)
            safe_stem = "".join(
                c if c.isalnum() or c in "-_" else "_" for c in item.source_file.stem
            )[:80]
            file_hash = hashlib.sha256(item.source_file.read_bytes()).hexdigest()
            target = self.settings.artifacts_path / "raw" / f"{safe_stem}-{file_hash[:12]}.json"
            if not target.exists():
                shutil.copy2(item.source_file, target)

    def _request(self, items: list[SourceProblem]) -> LLMResponse:
        for attempt in range(self.settings.max_retries + 1):
            try:
                for item in items:
                    self.state.record_request_attempt(item)
                return self.adapter.generate(SYSTEM_PROMPT, build_prompt(items))
            except LLMError as exc:
                if not exc.transient or attempt >= self.settings.max_retries:
                    raise
                delay = min(
                    self.settings.backoff_max_seconds,
                    self.settings.backoff_base_seconds * (2**attempt),
                )
                self.sleeper(delay)
        raise AssertionError("unreachable")

    def _process_batch(self, items: list[SourceProblem], *, allow_split: bool) -> tuple[int, int]:
        for item in items:
            self.state.mark_processing(item, self.adapter.model, self.adapter.effort)
        try:
            response = self._request(items)
            parsed = parse_response(response.text)
        except LLMError as exc:
            if exc.status_code == 429:
                for item in items:
                    self.state.mark_pending(item, str(exc))
                raise
            for item in items:
                self._fail(item, f"LLM request failed: {exc}")
            return 0, len(items)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            if allow_split and len(items) > 1:
                total = [self._process_batch([item], allow_split=False) for item in items]
                return sum(x for x, _ in total), sum(y for _, y in total)
            self._fail(items[0], f"Malformed LLM response: {exc}")
            return 0, 1

        by_key: dict[str, dict] = {}
        for result in parsed["results"]:
            if (
                isinstance(result, dict)
                and isinstance(result.get("source_key"), str)
                and result["source_key"] not in by_key
            ):
                by_key[result["source_key"]] = result
        completed = failed = 0
        for item in items:
            result = by_key.get(item.key)
            if result is None:
                if allow_split and len(items) > 1:
                    good, bad = self._process_batch([item], allow_split=False)
                    completed += good
                    failed += bad
                else:
                    self._fail(item, "LLM response omitted this source_key")
                    failed += 1
                continue
            try:
                artifact = self._materialize(item, result, response.request_id)
                self.state.mark_completed(item, artifact, response.request_id)
                completed += 1
            except (
                OSError,
                RuntimeError,
                TypeError,
                UnicodeError,
                ValueError,
                PackageValidationError,
            ) as exc:
                if allow_split and len(items) > 1:
                    good, bad = self._process_batch([item], allow_split=False)
                    completed += good
                    failed += bad
                else:
                    self._fail(item, f"Package validation failed: {exc}")
                    failed += 1
        return completed, failed

    def _materialize(self, item: SourceProblem, result: dict, request_id: str | None) -> Path:
        package = result.get("package")
        if not isinstance(package, dict):
            raise TypeError("package must be an object")
        result = dict(result)
        package = dict(package)
        # Some models follow the semantic grouping but nest file contents inside
        # `package`. Accept that harmless shape drift and restore the strict
        # on-disk boundary before schema validation.
        for field in ("reference_solution", "test_generator", "test_strategy"):
            nested = package.pop(field, None)
            if field not in result and nested is not None:
                result[field] = nested
        package["provenance"] = {
            "source_id": item.problem["id"],
            "source_hash": item.source_hash,
            "source_name": item.source["name"],
            "source_url": item.problem.get("source_url") or item.source.get("url"),
            "original_title": item.problem["title"],
        }
        package["generation"] = {
            "generator_version": __version__,
            "model": self.adapter.model,
            "effort": "xhigh",
            "generated_at": datetime.now(UTC).isoformat(),
            "request_id": request_id,
        }
        validate_package_json(package)
        for field in ("reference_solution", "test_generator", "test_strategy"):
            if not isinstance(result.get(field), str) or not result[field].strip():
                raise ValueError(f"missing {field}")
            if len(result[field].encode("utf-8")) > 1024 * 1024:
                raise ValueError(f"{field} exceeds 1 MiB")
        safe_key = "".join(c if c.isalnum() or c in "-_" else "_" for c in item.key)[:80]
        staging = (
            self.settings.artifacts_path
            / "processing"
            / f"{safe_key}-{item.source_hash[:12]}-{os.getpid()}"
        )
        final = (
            self.settings.artifacts_path
            / "completed"
            / f"{package['slug']}-{item.source_hash[:12]}"
        )
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True)
        try:
            (staging / "problem.json").write_text(
                json.dumps(package, ensure_ascii=False, indent=2) + "\n", "utf-8"
            )
            (staging / "reference.cpp").write_text(
                result["reference_solution"].rstrip() + "\n", "utf-8"
            )
            (staging / "generator.py").write_text(result["test_generator"].rstrip() + "\n", "utf-8")
            (staging / "test-strategy.md").write_text(
                result["test_strategy"].rstrip() + "\n", "utf-8"
            )
            snapshot = {
                "source": item.source,
                "problem": item.problem,
                "source_file": item.source_file.name,
                "source_hash": item.source_hash,
            }
            (staging / "original-source.json").write_text(
                json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", "utf-8"
            )
            validate_package(staging, write_tests=True, sync_test_metadata=True)
            if final.exists():
                try:
                    validate_package(final)
                    shutil.rmtree(staging)
                except (OSError, UnicodeError, ValueError, PackageValidationError):
                    suffix = 1
                    candidate = final.with_name(f"{final.name}-retry-{suffix}")
                    while candidate.exists():
                        suffix += 1
                        candidate = final.with_name(f"{final.name}-retry-{suffix}")
                    final = candidate
                    staging.rename(final)
            else:
                staging.rename(final)
            return final
        except Exception:
            if staging.exists():
                failed = self.settings.artifacts_path / "failed" / staging.name
                if failed.exists():
                    shutil.rmtree(failed)
                staging.rename(failed)
            raise

    def _recover_completed_artifact(self, item: SourceProblem) -> bool:
        for problem_path in self.settings.artifacts_path.glob("completed/*/problem.json"):
            try:
                data = json.loads(problem_path.read_text("utf-8"))
                if data.get("provenance", {}).get("source_hash") == item.source_hash:
                    if data.get("schema_version") == "1.0":
                        migrate_package(problem_path.parent)
                        data = json.loads(problem_path.read_text("utf-8"))
                    else:
                        validate_package(problem_path.parent)
                    self.state.mark_completed(
                        item, problem_path.parent, data.get("generation", {}).get("request_id")
                    )
                    return True
            except (OSError, UnicodeError, json.JSONDecodeError, PackageValidationError):
                continue
        return False

    def _fail(self, item: SourceProblem, message: str) -> None:
        self.state.mark_failed(item, message)
        safe_key = "".join(c if c.isalnum() or c in "-_" else "_" for c in item.key)[:80]
        diagnostic = (
            self.settings.artifacts_path
            / "failed"
            / f"{safe_key}-{item.source_hash[:12]}.error.txt"
        )
        diagnostic.write_text(message.rstrip() + "\n", "utf-8")
