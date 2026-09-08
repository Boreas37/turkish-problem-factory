from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from .errors import PackageValidationError
from .sandbox import run_generator, run_limited
from .schema import diagnostics, load_and_validate


def normalized(data: bytes | str) -> str:
    if isinstance(data, bytes):
        data = data.decode("utf-8", "strict")
    stripped = data.replace("\r\n", "\n").rstrip()
    if not stripped:
        return ""
    return "\n".join(line.rstrip() for line in stripped.split("\n")) + "\n"


def _compile(source: Path, executable: Path) -> None:
    cpp = source.read_text("utf-8")
    forbidden = {
        r"#\s*include\s*[<\"](?:fstream|filesystem|unistd\.h|sys/|netinet/|arpa/)": "host filesystem/process/network header",
        r"\b(?:socket|connect|accept|bind|listen|fork|popen|fopen|dlopen|getenv)\s*\(": "host access API",
        r"\b(?:std::)?system\s*\(": "shell execution API",
        r"\b(?:exec[lvpe]*|posix_spawn)\s*\(": "process execution API",
        r"\b(?:asm|__asm__)\b": "inline assembly",
        r"/(?:etc|proc|sys|dev|Users|home)/": "absolute host path",
    }
    for pattern, reason in forbidden.items():
        if re.search(pattern, cpp):
            raise PackageValidationError([f"reference solution contains forbidden {reason}"])
    compiler = shutil.which("g++")
    if not compiler:
        raise PackageValidationError(["g++ was not found; C++20 validation is required"])
    try:
        result = run_limited(
            [
                compiler,
                "-std=c++20",
                "-O2",
                "-pipe",
                "-Wall",
                "-Wextra",
                "-Werror",
                str(source),
                "-o",
                str(executable),
            ],
            cwd=source.parent,
            timeout_ms=20000,
            memory_mb=1024,
            output_kb=4096,
            process_limit=32,
        )
    finally:
        (source.parent / "xcrun_db").unlink(missing_ok=True)
    if result.returncode:
        raise PackageValidationError(
            [
                "reference solution does not compile: "
                + result.stderr.decode("utf-8", "replace")[:4000]
            ]
        )


TEST_CATEGORIES = {"edge", "boundary", "random", "adversarial", "stress", "generated"}


def build_test_entry(index: int, *, hidden: bool, category: str) -> dict:
    prefix = "hidden" if hidden else "sample"
    ordinal = index + 1
    return {
        "id": f"{prefix}-{ordinal:04d}",
        "input_file": f"tests/{index:04d}.in",
        "output_file": f"tests/{index:04d}.out",
        "hidden": hidden,
        "weight": 1 if hidden else 0,
        "category": category,
    }


def _generated_cases(value: object) -> list[tuple[str, str]]:
    if not isinstance(value, list) or not value:
        raise PackageValidationError(["generator must output a non-empty JSON array"])
    cases: list[tuple[str, str]] = []
    for index, item in enumerate(value):
        if isinstance(item, str):
            cases.append((item, "generated"))
            continue
        if not isinstance(item, dict) or set(item) != {"input", "category"}:
            raise PackageValidationError(
                [f"generator item {index} must be a string or an input/category object"]
            )
        stdin, category = item["input"], item["category"]
        if category == "sample":
            category = "generated"
        if not isinstance(stdin, str) or category not in TEST_CATEGORIES:
            raise PackageValidationError([f"generator item {index} has invalid input/category"])
        cases.append((stdin, category))
    return cases


def validate_package(
    path: Path, *, write_tests: bool = False, sync_test_metadata: bool = False
) -> dict:
    path = path.resolve()
    errors: list[str] = []
    required = [
        "problem.json",
        "reference.cpp",
        "generator.py",
        "test-strategy.md",
        "original-source.json",
    ]
    for name in required:
        if not (path / name).is_file():
            errors.append(f"missing {name}")
    if errors:
        raise PackageValidationError(errors)
    problem = load_and_validate(path / "problem.json", "problem-v1.json")
    executable = path / ".reference.bin"
    try:
        _compile(path / "reference.cpp", executable)
        first = run_generator(path / "generator.py")
        second = run_generator(path / "generator.py")
        if first != second:
            raise PackageValidationError(["test generator is not deterministic"])
        try:
            generated = json.loads(first)
        except json.JSONDecodeError as exc:
            raise PackageValidationError([f"generator output is not JSON: {exc}"]) from exc
        generated_cases = _generated_cases(generated)
        if len(generated_cases) > 500:
            raise PackageValidationError(["generator emitted more than 500 cases"])
        encoded_sizes = [len(stdin.encode("utf-8")) for stdin, _ in generated_cases]
        if any(size > 2 * 1024 * 1024 for size in encoded_sizes):
            raise PackageValidationError(["a generated input exceeds 2 MiB"])
        if sum(encoded_sizes) > 16 * 1024 * 1024:
            raise PackageValidationError(["generated inputs exceed 16 MiB in total"])
        cases = [
            (sample["input"], sample["output"], True, "sample") for sample in problem["samples"]
        ]
        cases.extend((stdin, None, False, category) for stdin, category in generated_cases)
        expected_tests = [
            build_test_entry(index, hidden=not sample, category=category)
            for index, (_stdin, _output, sample, category) in enumerate(cases)
        ]
        if not sync_test_metadata and problem["tests"] != expected_tests:
            errors.append("test metadata does not match generated test files")
        tests_dir = path / "tests"
        if write_tests:
            tests_dir.mkdir(exist_ok=True)
        for index, (stdin, stated_output, sample, _category) in enumerate(cases):
            run = run_limited(
                [str(executable)],
                cwd=path,
                stdin=stdin.encode(),
                timeout_ms=problem["wall_time_limit_ms"],
                cpu_time_ms=problem["time_limit_ms"],
                memory_mb=max(1, (problem["memory_limit_kb"] + 1023) // 1024),
                output_kb=problem["output_limit_kb"],
            )
            if run.returncode:
                errors.append(
                    f"case {index}: reference exited {run.returncode}: {run.stderr.decode('utf-8', 'replace')[:500]}"
                )
                continue
            actual = normalized(run.stdout)
            if sample and normalized(stated_output or "") != actual:
                errors.append(f"sample {index}: declared output differs from reference output")
            input_file = tests_dir / f"{index:04d}.in"
            output_file = tests_dir / f"{index:04d}.out"
            if write_tests:
                input_file.write_text(stdin, "utf-8")
                output_file.write_text(actual, "utf-8")
            else:
                if not input_file.is_file() or not output_file.is_file():
                    errors.append(f"case {index}: referenced test files are missing")
                    continue
                if input_file.is_symlink() or output_file.is_symlink():
                    errors.append(f"case {index}: test files must not be symbolic links")
                    continue
                if input_file.read_text("utf-8") != stdin:
                    errors.append(f"case {index}: input file differs from deterministic generator")
                if normalized(output_file.read_text("utf-8")) != actual:
                    errors.append(f"case {index}: output file differs from reference oracle")
        if errors:
            raise PackageValidationError(errors)
        if sync_test_metadata:
            problem["tests"] = expected_tests
            validate_package_json(problem)
            (path / "problem.json").write_text(
                json.dumps(problem, ensure_ascii=False, indent=2) + "\n", "utf-8"
            )
        return {"cases": len(cases), "generated_cases": len(generated_cases)}
    finally:
        executable.unlink(missing_ok=True)


def validate_package_json(value: dict) -> None:
    errors = diagnostics(value, "problem-v1.json")
    if (
        isinstance(value.get("wall_time_limit_ms"), int)
        and isinstance(value.get("time_limit_ms"), int)
        and value["wall_time_limit_ms"] < value["time_limit_ms"]
    ):
        errors.append("wall_time_limit_ms must be greater than or equal to time_limit_ms")
    text = " ".join(
        str(value.get(field, ""))
        for field in ("title", "statement", "input_description", "output_description")
    ).lower()
    words = set(re.findall(r"[^\W\d_]+", text, flags=re.UNICODE))
    turkish_markers = {
        "ve",
        "bir",
        "verilen",
        "girdi",
        "çıktı",
        "satır",
        "sayı",
        "sayısı",
        "yazdırın",
    }
    if len(words & turkish_markers) < 2 and not set("çğıöşü") & set(text):
        errors.append("Turkish language check failed for user-facing problem text")
    if errors:
        raise PackageValidationError(errors)
