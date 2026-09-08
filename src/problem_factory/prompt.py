from __future__ import annotations

import json
from typing import Any

from .source import SourceProblem

SYSTEM_PROMPT = """You are a meticulous Turkish competitive-programming problem editor.
Return JSON only. Convert each supplied source into a deterministic, machine-testable Turkish
C++20 stdin/stdout problem. Do not change the mathematical task. Never include network access,
filesystem access, subprocesses, dynamic code execution, nondeterministic seeds, or interactive I/O.
Reference solutions must be complete, portable C++20 programs using explicit standard-library
headers; never use non-standard convenience headers such as <bits/stdc++.h>. Generators must be deterministic Python 3
programs printing one JSON array of objects with input and category fields; use a fixed seed and compact loops to create
edge, boundary, adversarial, and stress cases. Do not print expected outputs: the C++ oracle does that.
Stress cases should expose obviously inferior algorithms where constraints warrant it.
"""


def build_prompt(items: list[SourceProblem]) -> str:
    contract: dict[str, Any] = {
        "results": [
            {
                "source_key": "exact supplied source_key",
                "package": {
                    "schema_version": "1.1",
                    "slug": "turkish-ascii-slug",
                    "title": "Turkish title",
                    "statement": "Turkish statement",
                    "input_description": "Turkish input",
                    "output_description": "Turkish output",
                    "constraints": ["..."],
                    "samples": [{"input": "...", "output": "...", "explanation": None}],
                    "tags": ["..."],
                    "topics": ["..."],
                    "difficulty": "kolay|orta|zor",
                    "expected_time_complexity": "O(...)",
                    "expected_space_complexity": "O(...)",
                    "language": "cpp",
                    "cpp_standard": "c++20",
                    "program_type": "stdin_stdout",
                    "time_limit_ms": 1000,
                    "wall_time_limit_ms": 2000,
                    "memory_limit_kb": 262144,
                    "output_limit_kb": 1024,
                    "output_mode": "normalized_exact",
                    "float_tolerance": None,
                    "tests": [
                        {
                            "id": "sample-0001",
                            "input_file": "tests/0000.in",
                            "output_file": "tests/0000.out",
                            "hidden": False,
                            "weight": 0,
                            "category": "sample",
                        }
                    ],
                },
                "reference_solution": "complete C++20 source",
                "test_generator": "deterministic Python source printing JSON array of {input, category} objects",
                "test_strategy": "Turkish description of coverage and complexity discrimination",
            }
        ]
    }
    sources = [{"source_key": item.key, **item.prompt_value()} for item in items]
    return (
        "Produce exactly one result per source. The pipeline injects provenance and generation metadata; "
        "do not include them. Required response shape:\n"
        + json.dumps(contract, ensure_ascii=False)
        + "\nSources:\n"
        + json.dumps(sources, ensure_ascii=False, sort_keys=True)
    )


def parse_response(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 3 and lines[-1].strip() == "```":
            stripped = "\n".join(lines[1:-1])
            if stripped.lstrip().startswith("json"):
                stripped = stripped.lstrip()[4:].lstrip("\r\n")
    value = json.loads(stripped)
    if not isinstance(value, dict) or not isinstance(value.get("results"), list):
        raise TypeError("response must be an object containing a results array")
    return value
