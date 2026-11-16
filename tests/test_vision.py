"""Vision: default extract-the-question prompt shape, live Groq vision
model (qwen/qwen3.8-27b), <think> stripping, no-provider-key 503.
Provider HTTP is mocked — no real calls.
"""
import pytest

import app.providers as providers
from tests.conftest import auth, set_provider_key

TINY_PNG = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


@pytest.fixture()
def mock_vision(monkeypatch):
    captured = {}

    async def fake_post_json(url, headers, payload):
        captured["url"] = url
        captured["payload"] = payload
        return {
            "choices": [
                {
                    "message": {
                        "content": "<think>some reasoning here</think>Write a function that reverses a string."
                    }
                }
            ],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20},
        }

    monkeypatch.setattr(providers, "_post_json", fake_post_json)
    return captured


def test_vision_prompt_shape_and_model(client, user, db, mock_vision):
    set_provider_key(db, "groq", "gsk_test_key")
    r = client.post(
        "/api/ai/vision",
        json={"image": TINY_PNG},
        headers=auth(user["token"]),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # <think> block stripped — only the extracted question remains.
    assert body["text"] == "Write a function that reverses a string."
    assert body["provider"] == "groq"
    assert body["model"] == "qwen/qwen3.8-27b"

    payload = mock_vision["payload"]
    assert payload["model"] == "qwen/qwen3.8-27b"
    assert "groq.com" in mock_vision["url"]
    content = payload["messages"][0]["content"]
    text_part = [p for p in content if p["type"] == "text"][0]["text"]
    # The default prompt is the extract-the-question prompt.
    assert "word for word" in text_part
    assert "NO QUESTION FOUND" in text_part
    assert "ONLY the extracted question" in text_part
    image_part = [p for p in content if p["type"] == "image_url"][0]
    assert image_part["image_url"]["url"] == TINY_PNG


def test_vision_custom_prompt_passed_through(client, user, db, mock_vision):
    set_provider_key(db, "groq", "gsk_test_key")
    r = client.post(
        "/api/ai/vision",
        json={"image": TINY_PNG, "prompt": "Describe this image briefly."},
        headers=auth(user["token"]),
    )
    assert r.status_code == 200
    text_part = [
        p
        for p in mock_vision["payload"]["messages"][0]["content"]
        if p["type"] == "text"
    ][0]["text"]
    assert text_part == "Describe this image briefly."


def test_vision_no_provider_key_503(client, user):
    r = client.post(
        "/api/ai/vision",
        json={"image": TINY_PNG},
        headers=auth(user["token"]),
    )
    assert r.status_code == 503
    assert r.json()["detail"]["error"] == "NO_PROVIDER_KEY"


def test_vision_requires_auth(client):
    r = client.post("/api/ai/vision", json={"image": TINY_PNG})
    assert r.status_code == 401
