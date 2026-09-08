from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from .errors import PackageValidationError


def load_schema(name: str) -> dict[str, Any]:
    return json.loads(files("problem_factory").joinpath("schemas", name).read_text("utf-8"))


def diagnostics(instance: Any, schema_name: str) -> list[str]:
    validator = Draft202012Validator(load_schema(schema_name), format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.absolute_path))
    return [f"{'.'.join(map(str, e.absolute_path)) or '$'}: {e.message}" for e in errors]


def load_and_validate(path: Path, schema_name: str) -> Any:
    try:
        value = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PackageValidationError([f"{path}: invalid JSON: {exc}"]) from exc
    problems = diagnostics(value, schema_name)
    if problems:
        raise PackageValidationError(problems)
    return value
