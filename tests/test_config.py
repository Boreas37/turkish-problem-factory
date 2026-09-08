from pathlib import Path

import pytest

from problem_factory.config import Settings
from problem_factory.errors import ConfigurationError


def test_effort_cannot_be_lowered(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("OPENCODE_ZEN_EFFORT", "high")
    with pytest.raises(ConfigurationError, match="must be xhigh"):
        Settings.from_env(tmp_path)


def test_defaults_are_required_profile(monkeypatch, tmp_path: Path):
    for key in ("OPENCODE_ZEN_MODEL", "OPENCODE_ZEN_EFFORT"):
        monkeypatch.delenv(key, raising=False)
    settings = Settings.from_env(tmp_path)
    assert settings.model == "muse-spark-1.3-contributor-free"
    assert settings.effort == "xhigh"
    assert settings.batch_size == 5
