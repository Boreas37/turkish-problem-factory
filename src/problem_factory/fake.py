from __future__ import annotations

from pathlib import Path

from .llm import LLMResponse


class FileFakeAdapter:
    model = "muse-spark-1.3-contributor-free"
    effort = "xhigh"

    def __init__(self, response_file: Path):
        self.response_file = response_file
        self.calls = 0

    def generate(self, system: str, prompt: str) -> LLMResponse:
        self.calls += 1
        return LLMResponse(self.response_file.read_text("utf-8"), f"fake-{self.calls}")
