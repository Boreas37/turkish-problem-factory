from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .errors import ConfigurationError


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer") from exc


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be numeric") from exc


@dataclass(frozen=True)
class Settings:
    root: Path
    api_key: str | None
    base_url: str
    model: str
    effort: str
    batch_size: int
    max_retries: int
    request_timeout_seconds: int
    backoff_base_seconds: float
    backoff_max_seconds: float

    @classmethod
    def from_env(cls, root: Path | str = ".") -> Settings:
        settings = cls(
            root=Path(root).resolve(),
            api_key=os.getenv("OPENCODE_ZEN_API_KEY"),
            base_url=os.getenv("OPENCODE_ZEN_BASE_URL", "https://opencode.ai/zen/v1").rstrip("/"),
            model=os.getenv("OPENCODE_ZEN_MODEL", "muse-spark-1.3-contributor-free"),
            effort=os.getenv("OPENCODE_ZEN_EFFORT", "xhigh"),
            batch_size=_int("PROBLEM_FACTORY_BATCH_SIZE", 5),
            max_retries=_int("PROBLEM_FACTORY_MAX_RETRIES", 4),
            request_timeout_seconds=_int("PROBLEM_FACTORY_REQUEST_TIMEOUT_SECONDS", 180),
            backoff_base_seconds=_float("PROBLEM_FACTORY_BACKOFF_BASE_SECONDS", 2.0),
            backoff_max_seconds=_float("PROBLEM_FACTORY_BACKOFF_MAX_SECONDS", 60.0),
        )
        if settings.effort != "xhigh":
            raise ConfigurationError("OPENCODE_ZEN_EFFORT must be xhigh; lower effort is forbidden")
        if settings.batch_size < 1:
            raise ConfigurationError("batch size must be at least 1")
        if settings.max_retries < 0:
            raise ConfigurationError("max retries cannot be negative")
        return settings

    @property
    def state_path(self) -> Path:
        return self.root / "state.db"

    @property
    def artifacts_path(self) -> Path:
        return self.root / "artifacts"
