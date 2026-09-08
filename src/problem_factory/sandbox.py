from __future__ import annotations

import ast
import os
import resource
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RunResult:
    returncode: int
    stdout: bytes
    stderr: bytes


def _limits(memory_mb: int, output_kb: int, cpu_seconds: int, process_limit: int):
    def set_soft(kind: int, requested: int) -> None:
        try:
            _soft, hard = resource.getrlimit(kind)
            value = requested if hard == resource.RLIM_INFINITY else min(requested, hard)
            resource.setrlimit(kind, (value, hard))
        except (OSError, ValueError):
            # Some kernels expose a resource constant but reject changing it.
            # Wall-clock and file-backed output limits still remain active.
            pass

    def apply() -> None:
        set_soft(resource.RLIMIT_CPU, cpu_seconds)
        set_soft(resource.RLIMIT_AS, memory_mb * 1024 * 1024)
        set_soft(resource.RLIMIT_FSIZE, output_kb * 1024)
        set_soft(resource.RLIMIT_NOFILE, 32)
        # RLIMIT_NPROC is per-user on macOS; lowering it below the user's current
        # process count prevents the compiler itself from spawning.
        if sys.platform != "darwin" and hasattr(resource, "RLIMIT_NPROC"):
            set_soft(resource.RLIMIT_NPROC, process_limit)

    return apply


def run_limited(
    command: list[str],
    *,
    cwd: Path,
    stdin: bytes = b"",
    timeout_ms: int = 3000,
    cpu_time_ms: int | None = None,
    memory_mb: int = 256,
    output_kb: int = 1024,
    process_limit: int = 1,
) -> RunResult:
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "LANG": "C",
        "LC_ALL": "C",
        "HOME": str(cwd),
        "TMPDIR": str(cwd),
    }
    with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
        try:
            result = subprocess.run(
                command,
                cwd=cwd,
                input=stdin,
                stdout=stdout_file,
                stderr=stderr_file,
                timeout=timeout_ms / 1000,
                env=env,
                preexec_fn=_limits(
                    memory_mb,
                    output_kb,
                    max(1, ((cpu_time_ms or timeout_ms) + 999) // 1000),
                    process_limit,
                ),
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"timed out after {timeout_ms} ms") from exc
        stdout_file.seek(0)
        stderr_file.seek(0)
        stdout = stdout_file.read(output_kb * 1024 + 1)
        stderr = stderr_file.read(output_kb * 1024 + 1)
    if len(stdout) > output_kb * 1024:
        raise RuntimeError(f"stdout exceeded {output_kb} KiB")
    return RunResult(result.returncode, stdout, stderr)


def audit_generator(source: str) -> None:
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        location = f"line {exc.lineno}" if exc.lineno else "unknown line"
        raise ValueError(f"generator syntax error at {location}: {exc.msg}") from exc
    allowed_imports = {"json", "random", "math", "itertools"}
    banned_names = {"open", "exec", "eval", "compile", "__import__", "input", "breakpoint"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name.split(".")[0] not in allowed_imports for alias in node.names):
                raise ValueError("generator imports a forbidden module")
        elif isinstance(node, ast.ImportFrom):
            if not node.module or node.module.split(".")[0] not in allowed_imports:
                raise ValueError("generator imports a forbidden module")
        elif isinstance(node, ast.Name) and node.id in banned_names:
            raise ValueError(f"generator uses forbidden name: {node.id}")
        elif isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            raise ValueError("generator uses forbidden dunder attribute")


def run_generator(path: Path, *, timeout_ms: int = 5000) -> bytes:
    audit_generator(path.read_text("utf-8"))
    result = run_limited(
        [sys.executable, "-I", "-S", str(path)],
        cwd=path.parent,
        timeout_ms=timeout_ms,
        memory_mb=256,
        output_kb=8192,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"test generator failed: {result.stderr.decode('utf-8', 'replace')[:2000]}"
        )
    return result.stdout
