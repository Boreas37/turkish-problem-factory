import json

from problem_factory.llm import ZenAdapter


class FakeHTTPResponse:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self, *_args):
        return json.dumps({"id": "response-1", "output_text": "{}"}).encode()


def test_zen_request_always_sends_xhigh_and_idempotency_key(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeHTTPResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    adapter = ZenAdapter(
        api_key="secret",
        base_url="https://opencode.ai/zen/v1",
        model="muse-spark-1.3",
        effort="xhigh",
        timeout=12,
    )
    response = adapter.generate("system", "prompt")
    payload = json.loads(captured["request"].data)
    assert payload["model"] == "muse-spark-1.3"
    assert payload["reasoning"] == {"effort": "xhigh"}
    assert captured["request"].get_header("Idempotency-key")
    assert captured["request"].get_header("X-opencode-session").startswith("problem-factory-")
    assert captured["request"].get_header("User-agent") == "turkish-problem-factory/0.2.0"
    assert captured["request"].get_header("Accept") == "application/json"
    assert captured["timeout"] == 12
    assert response.request_id == "response-1"
