import copy
import json
from pathlib import Path

import pytest

from problem_factory.errors import PackageValidationError
from problem_factory.schema import diagnostics, load_and_validate
from problem_factory.validation import normalized, validate_package

ROOT = Path(__file__).parents[1]


def test_example_source_matches_schema():
    data = load_and_validate(ROOT / "examples/sources/basic.json", "source-v1.json")
    assert len(data["problems"]) == 1


def test_platform_contract_has_cpp20_tests_but_no_judge0_id():
    package_path = ROOT / "examples/generated/iki-sayinin-toplami-1b4cb76cf359"
    problem = load_and_validate(package_path / "problem.json", "problem-v1.json")
    assert problem["schema_version"] == "1.1"
    assert problem["language"] == "cpp"
    assert problem["cpp_standard"] == "c++20"
    assert problem["output_mode"] == "normalized_exact"
    assert problem["float_tolerance"] is None
    assert "language_id" not in problem
    assert problem["wall_time_limit_ms"] >= problem["time_limit_ms"]
    assert problem["memory_limit_kb"] == 131072
    assert problem["tests"][0]["hidden"] is False
    assert problem["tests"][0]["category"] == "sample"
    assert any(test["hidden"] for test in problem["tests"])
    for test in problem["tests"]:
        assert (package_path / test["input_file"]).is_file()
        assert (package_path / test["output_file"]).is_file()
    with_judge0_id = copy.deepcopy(problem)
    with_judge0_id["language_id"] = 105
    assert any("language_id" in error for error in diagnostics(with_judge0_id, "problem-v1.json"))
    bad_reference = copy.deepcopy(problem)
    bad_reference["tests"][0]["input_file"] = "../outside.in"
    assert diagnostics(bad_reference, "problem-v1.json")


def test_normalized_exact_only_ignores_trailing_whitespace():
    assert normalized("1 2  \r\n3\n\n") == normalized("1 2\n3")
    assert normalized("1  2\n") != normalized("1 2\n")
    assert normalized(" 1\n") != normalized("1\n")


def test_generator_must_be_deterministic(tmp_path: Path):
    response = json.loads((ROOT / "examples/fake-responses/basic.json").read_text("utf-8"))[
        "results"
    ][0]
    package = response["package"]
    package["provenance"] = {
        "source_id": "x",
        "source_hash": "a" * 64,
        "source_name": "x",
        "source_url": None,
        "original_title": "x",
    }
    package["generation"] = {
        "generator_version": "test",
        "model": "muse-spark-1.3-contributor-free",
        "effort": "xhigh",
        "generated_at": "2026-01-01T00:00:00+00:00",
        "request_id": None,
    }
    (tmp_path / "problem.json").write_text(json.dumps(package), "utf-8")
    (tmp_path / "reference.cpp").write_text(response["reference_solution"], "utf-8")
    (tmp_path / "generator.py").write_text(
        "import json\nimport random\nprint(json.dumps([str(random.random())]))\n", "utf-8"
    )
    (tmp_path / "test-strategy.md").write_text("test", "utf-8")
    (tmp_path / "original-source.json").write_text("{}", "utf-8")
    with pytest.raises(PackageValidationError, match="not deterministic"):
        validate_package(tmp_path)
