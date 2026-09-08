from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

from .config import Settings
from .errors import FactoryError
from .fake import FileFakeAdapter
from .judge0 import Judge0Adapter, Judge0Settings, smoke_package
from .llm import ZenAdapter
from .migration import migrate_package
from .pipeline import Pipeline
from .source import discover_sources
from .state import StateStore
from .validation import validate_package


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="problem-factory")
    root.add_argument("--root", type=Path, default=Path("."), help="state/artifact project root")
    commands = root.add_subparsers(dest="command", required=True)
    source = commands.add_parser("validate-source")
    source.add_argument("path", type=Path)
    process = commands.add_parser("process")
    process.add_argument("path", type=Path)
    process.add_argument("--batch-size", type=int)
    process.add_argument("--fake-response", type=Path, help="offline testing only")
    resume = commands.add_parser("resume")
    resume.add_argument("path", type=Path)
    resume.add_argument("--fake-response", type=Path)
    retry = commands.add_parser("retry-failed")
    retry.add_argument("path", type=Path)
    retry.add_argument("--fake-response", type=Path)
    commands.add_parser("status")
    package = commands.add_parser("validate-package")
    package.add_argument("path", type=Path)
    migration = commands.add_parser("migrate-package")
    migration.add_argument("path", type=Path)
    smoke = commands.add_parser("judge0-smoke")
    smoke.add_argument("path", type=Path)
    smoke.add_argument("--max-tests", type=int, default=3)
    return root


def _adapter(settings: Settings, fake_response: Path | None):
    if fake_response:
        return FileFakeAdapter(fake_response)
    return ZenAdapter(
        api_key=settings.api_key,
        base_url=settings.base_url,
        model=settings.model,
        effort=settings.effort,
        timeout=settings.request_timeout_seconds,
    )


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        settings = Settings.from_env(args.root)
        if args.command == "validate-source":
            items = list(discover_sources(args.path))
            print(json.dumps({"valid": True, "problems": len(items)}, ensure_ascii=False))
        elif args.command == "validate-package":
            print(json.dumps({"valid": True, **validate_package(args.path)}, ensure_ascii=False))
        elif args.command == "migrate-package":
            print(json.dumps(migrate_package(args.path), ensure_ascii=False))
        elif args.command == "judge0-smoke":
            judge0 = Judge0Adapter(Judge0Settings.from_env())
            print(
                json.dumps(
                    smoke_package(args.path, judge0, max_tests=args.max_tests), ensure_ascii=False
                )
            )
        elif args.command == "status":
            rows = StateStore(settings.state_path).rows()
            summary: dict[str, int] = {}
            for row in rows:
                summary[row["status"]] = summary.get(row["status"], 0) + 1
            print(
                json.dumps(
                    {"summary": summary, "items": [dict(row) for row in rows]},
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            if getattr(args, "batch_size", None):
                if args.batch_size < 1:
                    raise ValueError("batch size must be at least 1")
                settings = replace(settings, batch_size=args.batch_size)
            pipeline = Pipeline(settings, _adapter(settings, getattr(args, "fake_response", None)))
            result = pipeline.process(
                args.path, retry_failed=args.command in {"resume", "retry-failed"}
            )
            print(json.dumps(result, ensure_ascii=False))
        return 0
    except (FactoryError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
