import copy
import json
from pathlib import Path

from problem_factory.migration import migrate_problem_data
from problem_factory.schema import diagnostics

ROOT = Path(__file__).parents[1]


def test_legacy_package_migrates_without_judge0_fields():
    current = json.loads(
        (ROOT / "examples/generated/iki-sayinin-toplami-1b4cb76cf359/problem.json").read_text(
            "utf-8"
        )
    )
    legacy = {
        key: copy.deepcopy(current[key])
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
    legacy.update(
        {
            "schema_version": "1.0",
            "judge": {
                "language": "cpp",
                "cpp_standard": "c++20",
                "program_type": "stdin_stdout",
                "time_limit_ms": 1000,
                "memory_limit_mb": 128,
                "output_limit_kb": 64,
                "checker": {"type": "exact", "normalize_trailing_whitespace": True},
            },
            "classification": {
                "tags": current["tags"],
                "topic": current["topics"][0],
                "difficulty": current["difficulty"],
            },
            "complexity": {
                "time": current["expected_time_complexity"],
                "space": current["expected_space_complexity"],
            },
        }
    )
    migrated = migrate_problem_data(legacy)
    assert migrated["schema_version"] == "1.1"
    assert migrated["memory_limit_kb"] == 131072
    assert "judge" not in migrated
    assert "language_id" not in migrated
    assert diagnostics(migrated, "problem-v1.json") == []
