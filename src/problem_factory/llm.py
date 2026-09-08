from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol

from . import __version__
from .errors import ConfigurationError, LLMError


@dataclass(frozen=True)
class LLMResponse:
    text: str
    request_id: str | None = None


class LLMAdapter(Protocol):
    model: str
    effort: str

    def generate(self, system: str, prompt: str) -> LLMResponse: ...


class ZenAdapter:
    """Minimal OpenAI Responses-compatible adapter for OpenCode Zen."""

    def __init__(
        self, *, api_key: str | None, base_url: str, model: str, effort: str, timeout: int = 180
    ):
        if not api_key:
            raise ConfigurationError("OPENCODE_ZEN_API_KEY is required for real processing")
        if effort != "xhigh":
            raise ConfigurationError("Every Zen request must use xhigh effort")
        self.api_key, self.base_url, self.model, self.effort, self.timeout = (
            api_key,
            base_url.rstrip("/"),
            model,
            effort,
            timeout,
        )

    def generate(self, system: str, prompt: str) -> LLMResponse:
        payload = {
            "model": self.model,
            "reasoning": {"effort": "xhigh"},
            "input": [
                {"role": "system", "content": [{"type": "input_text", "text": system}]},
                {"role": "user", "content": [{"type": "input_text", "text": prompt}]},
            ],
        }
        request_fingerprint = hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode()
        ).hexdigest()
        request = urllib.request.Request(
            f"{self.base_url}/responses",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": f"turkish-problem-factory/{__version__}",
                "Idempotency-Key": request_fingerprint,
                "x-opencode-session": f"problem-factory-{request_fingerprint[:32]}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read(20 * 1024 * 1024 + 1)
                if len(raw) > 20 * 1024 * 1024:
                    raise LLMError("Zen response exceeded 20 MiB")
                body = json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read(2048).decode("utf-8", "replace")
            transient = exc.code in {408, 409, 425, 429} or exc.code >= 500
            raise LLMError(
                f"Zen HTTP {exc.code}: {detail}", status_code=exc.code, transient=transient
            ) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise LLMError(f"Zen network error: {exc}", transient=True) from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LLMError(f"Zen returned invalid JSON: {exc}") from exc
        try:
            text = body.get("output_text") or next(
                part["text"]
                for output in body["output"]
                if output.get("type") == "message"
                for part in output.get("content", [])
                if part.get("type") in {"output_text", "text"}
            )
        except (KeyError, StopIteration, TypeError) as exc:
            raise LLMError("Zen response did not contain output text") from exc
        return LLMResponse(text=text, request_id=body.get("id"))
