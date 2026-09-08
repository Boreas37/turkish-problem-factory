from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .schema import load_and_validate


@dataclass(frozen=True)
class SourceProblem:
    key: str
    source_hash: str
    source_file: Path
    source: dict[str, Any]
    problem: dict[str, Any]

    def prompt_value(self) -> dict[str, Any]:
        return {"source": self.source, "problem": self.problem, "source_hash": self.source_hash}


def canonical_hash(source: dict[str, Any], problem: dict[str, Any]) -> str:
    raw = json.dumps(
        {"source": source, "problem": problem},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def load_source_file(path: Path) -> list[SourceProblem]:
    doc = load_and_validate(path, "source-v1.json")
    result = []
    for problem in doc["problems"]:
        key = f"{doc['source']['name']}:{problem['id']}"
        result.append(
            SourceProblem(
                key, canonical_hash(doc["source"], problem), path.resolve(), doc["source"], problem
            )
        )
    return result


def discover_sources(path: Path) -> Iterator[SourceProblem]:
    files_to_read = [path] if path.is_file() else sorted(path.glob("*.json"))
    for file_path in files_to_read:
        yield from load_source_file(file_path)
