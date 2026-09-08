from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

from .errors import PackageValidationError
from .validation import build_test_entry, validate_package


def migrate_problem_data(problem: dict) -> dict:
    version = problem.get("schema_version")
    if version == "1.1":
        return dict(problem)
    if version != "1.0":
        raise PackageValidationError([f"unsupported schema_version for migration: {version}"])
    try:
        judge = problem["judge"]
        classification = problem["classification"]
        complexity = problem["complexity"]
        migrated = {
            key: problem[key]
            for key in (
                "slug",
                "title",
                "statement",
                "input_description",
                "output_description",
                "constraints",
                "samples",
                "provenance",
                "generation",
            )
        }
        migrated.update(
            {
                "schema_version": "1.1",
                "tags": classification["tags"],
                "topics": [classification["topic"]],
                "difficulty": classification["difficulty"],
                "expected_time_complexity": complexity["time"],
                "expected_space_complexity": complexity["space"],
                "language": judge["language"],
                "cpp_standard": judge["cpp_standard"],
                "program_type": judge["program_type"],
                "time_limit_ms": judge["time_limit_ms"],
                "wall_time_limit_ms": max(judge["time_limit_ms"] * 2, judge["time_limit_ms"]),
                "memory_limit_kb": judge["memory_limit_mb"] * 1024,
                "output_limit_kb": judge["output_limit_kb"],
                "output_mode": "normalized_exact",
                "float_tolerance": None,
                "tests": [
                    build_test_entry(index, hidden=False, category="sample")
                    for index, _sample in enumerate(problem["samples"])
                ],
            }
        )
    except (KeyError, TypeError) as exc:
        raise PackageValidationError([f"legacy package is malformed: {exc}"]) from exc
    return migrated


def migrate_package(path: Path) -> dict:
    path = path.resolve()
    source_problem = path / "problem.json"
    try:
        original_bytes = source_problem.read_bytes()
        problem = json.loads(original_bytes.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PackageValidationError([f"cannot read legacy problem.json: {exc}"]) from exc
    if problem.get("schema_version") == "1.1":
        result = validate_package(path)
        return {"migrated": False, **result}
    if not (path / "tests").is_dir():
        raise PackageValidationError(["legacy package has no tests directory; refusing migration"])
    migrated = migrate_problem_data(problem)
    with tempfile.TemporaryDirectory(prefix="problem-migration-", dir=path.parent) as temp:
        candidate = Path(temp) / "package"
        shutil.copytree(path, candidate)
        (candidate / "problem.json").write_text(
            json.dumps(migrated, ensure_ascii=False, indent=2) + "\n", "utf-8"
        )
        result = validate_package(candidate, write_tests=True, sync_test_metadata=True)
        replacement = path / ".problem.json.migrate.tmp"
        shutil.copy2(candidate / "problem.json", replacement)
        os.replace(replacement, source_problem)
    try:
        validate_package(path)
    except Exception:
        replacement = path / ".problem.json.migrate.rollback"
        replacement.write_bytes(original_bytes)
        os.replace(replacement, source_problem)
        raise
    return {"migrated": True, **result}
