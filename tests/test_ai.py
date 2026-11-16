"""AI proxy: chat happy path + provider error passthrough, /ai/status,
transcribe key routing. Provider HTTP is mocked — no real calls.
"""
import pytest

import app.providers as providers
from tests.conftest import auth, set_provider_key


@pytest.fixture()
def mock_chat(monkeypatch):
    captured = {}

    async def fake_post_json(url, headers, payload):
        captured["url"] = url
        captured["payload"] = payload
        return {
            "choices": [{"message": {"content": "Use two pointers."}}],
            "usage": {"prompt_tokens": 50, "completion_tokens": 10},
        }

    monkeypatch.setattr(providers, "_post_json", fake_post_json)
    return captured


def test_chat_groq_happy(client, user, db, mock_chat):
    set_provider_key(db, "groq", "gsk_test_key")
    r = client.post(
        "/api/ai/chat",
        json={"messages": [{"role": "user", "content": "How do I reverse a string?"}]},
        headers=auth(user["token"]),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["text"] == "Use two pointers."
    assert body["provider"] == "groq"
    assert body["model"] == "openai/gpt-oss-120b"
    assert mock_chat["payload"]["model"] == "openai/gpt-oss-120b"
    # The backend adds the Indian-English tone as the first system message;
    # the caller's own message follows unchanged.
    msgs = mock_chat["payload"]["messages"]
    assert msgs[0]["role"] == "system"
    assert "Indian English" in msgs[0]["content"]
    assert msgs[1]["content"] == "How do I reverse a string?"


def test_chat_tone_merges_into_client_system_message(client, user, db, mock_chat):
    set_provider_key(db, "groq", "gsk_test_key")
    r = client.post(
        "/api/ai/chat",
        json={"messages": [
            {"role": "system", "content": "You are a strict interview coach."},
            {"role": "user", "content": "hi"},
        ]},
        headers=auth(user["token"]),
    )
    assert r.status_code == 200, r.text
    msgs = mock_chat["payload"]["messages"]
    assert len([m for m in msgs if m["role"] == "system"]) == 1
    assert "You are a strict interview coach." in msgs[0]["content"]
    assert "Indian English" in msgs[0]["content"]
    assert msgs[1]["content"] == "hi"


def test_chat_no_provider_key_503(client, user):
    r = client.post(
        "/api/ai/chat",
        json={"messages": [{"role": "user", "content": "hi"}]},
        headers=auth(user["token"]),
    )
    assert r.status_code == 503
    assert r.json()["detail"]["error"] == "NO_PROVIDER_KEY"


def test_chat_provider_error_passthrough(client, user, db, monkeypatch):
    set_provider_key(db, "groq", "gsk_test_key")

    async def failing_post(url, headers, payload):
        raise providers.ProviderError("Incorrect API key provided")

    monkeypatch.setattr(providers, "_post_json", failing_post)
    r = client.post(
        "/api/ai/chat",
        json={"messages": [{"role": "user", "content": "hi"}]},
        headers=auth(user["token"]),
    )
    assert r.status_code == 502
    assert r.json()["error"] == "Incorrect API key provided"


def test_ai_status_unconfigured_then_configured(client, user, db):
    r = client.get("/api/ai/status", headers=auth(user["token"]))
    assert r.status_code == 200
    assert r.json()["configured"] is False
    assert r.json()["provider"] == "groq"
    set_provider_key(db, "groq", "gsk_test_key")
    r = client.get("/api/ai/status", headers=auth(user["token"]))
    assert r.json()["configured"] is True
    assert r.json()["chat_model"] == "openai/gpt-oss-120b"
    assert r.json()["vision_model"] == "qwen/qwen3.8-27b"


def test_transcribe_no_key_503(client, user):
    r = client.post(
        "/api/ai/transcribe",
        files={"audio": ("chunk.webm", b"fake-audio-bytes", "audio/webm")},
        headers=auth(user["token"]),
    )
    assert r.status_code == 503
    assert r.json()["detail"]["error"] == "NO_PROVIDER_KEY"


def test_transcribe_groq(client, user, db, monkeypatch):
    set_provider_key(db, "groq", "gsk_test_key")
    captured = {}

    async def fake_multipart(url, headers, files, data):
        captured["url"] = url
        captured["data"] = data
        return {"text": "What is a binary search tree?"}

    monkeypatch.setattr(providers, "_post_multipart", fake_multipart)
    r = client.post(
        "/api/ai/transcribe",
        files={"audio": ("chunk.webm", b"fake-audio-bytes", "audio/webm")},
        headers=auth(user["token"]),
    )
    assert r.status_code == 200, r.text
    assert r.json()["text"] == "What is a binary search tree?"
    assert "groq.com" in captured["url"]
    assert captured["data"]["model"] == "whisper-large-v3-turbo"
