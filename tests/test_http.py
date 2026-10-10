import io
import json

from common import http


class FakeUrlopen:
    """Records the Request it's given and returns `payload`."""

    def __init__(self, payload):
        self.payload = payload
        self.request = None

    def __call__(self, request, timeout):
        self.request = request
        return io.BytesIO(self.payload)


def test_fetch_json_get_sorts_params(monkeypatch):
    fake = FakeUrlopen(b'{"ok": true}')
    monkeypatch.setattr(http, "urlopen", fake)
    result = http.fetch_json(
        "https://api.example/x", {"q": "a b", "languages": "en"},
        {"Api-Key": "k"},
    )
    assert result == {"ok": True}
    request = fake.request
    assert request.full_url == "https://api.example/x?languages=en&q=a+b"
    assert request.get_method() == "GET"
    assert request.get_header("Api-key") == "k"
    assert request.get_header("Accept") == "application/json"


def test_fetch_posts_json_body(monkeypatch):
    fake = FakeUrlopen(b"raw")
    monkeypatch.setattr(http, "urlopen", fake)
    assert http.fetch("https://api.example/y", body={"id": 1}) == b"raw"
    request = fake.request
    assert request.get_method() == "POST"
    assert json.loads(request.data) == {"id": 1}
    assert request.get_header("Content-type") == "application/json"
