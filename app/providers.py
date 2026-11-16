"""AI provider clients: Groq, OpenAI, Gemini, Claude.

All calls go through `_post_json` / `_post_multipart` so tests can mock the
HTTP layer without any real provider call. Provider errors surface as
ProviderError with the provider's message (never a stack trace).

Vision default prompt extracts the question verbatim or "NO QUESTION FOUND".
Qwen models "think out loud" — <think>...</think> blocks are stripped from
vision (and chat) text before returning.
"""
import base64
import re

import httpx

VISION_PROMPT = (
    "Read this screenshot of an interview / coding question on screen. "
    "Extract the exact question or problem shown, word for word, including "
    "any code, numbers and constraints. Reply with ONLY the extracted "
    "question/problem text, nothing else. If no question is visible, reply "
    "with exactly: NO QUESTION FOUND"
)

THINK_RE = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)


class ProviderError(Exception):
    pass


def strip_think(text: str) -> str:
    return THINK_RE.sub("", text or "").strip()


async def _post_json(url: str, headers: dict, payload: dict) -> dict:
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(url, headers=headers, json=payload)
    try:
        data = resp.json()
    except Exception:
        data = {}
    if resp.status_code >= 400:
        msg = ""
        if isinstance(data, dict):
            err = data.get("error")
            if isinstance(err, dict):
                msg = err.get("message", "")
            elif isinstance(err, str):
                msg = err
            msg = msg or data.get("message", "")
        raise ProviderError(msg or f"Provider error {resp.status_code}")
    return data


async def _post_multipart(url: str, headers: dict, files: dict, data: dict) -> dict:
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(url, headers=headers, files=files, data=data)
    try:
        out = resp.json()
    except Exception:
        out = {}
    if resp.status_code >= 400:
        msg = ""
        if isinstance(out, dict):
            err = out.get("error")
            if isinstance(err, dict):
                msg = err.get("message", "")
            elif isinstance(err, str):
                msg = err
            msg = msg or out.get("message", "")
        raise ProviderError(msg or f"Provider error {resp.status_code}")
    return out


# ---------------------------------------------------------------- chat ----
def _openai_shape_chat(model: str, messages: list, temperature: float, max_tokens: int) -> dict:
    return {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }


def _gemini_contents(messages: list) -> tuple[list, dict | None]:
    """Convert OpenAI-style messages to Gemini contents + systemInstruction."""
    contents: list = []
    system = None
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        if isinstance(content, list):
            content = " ".join(
                str(p.get("text", "")) for p in content if isinstance(p, dict)
            )
        if role == "system":
            system = {"parts": [{"text": str(content)}]}
        else:
            contents.append(
                {"role": "model" if role == "assistant" else "user", "parts": [{"text": str(content)}]}
            )
    return contents, system


async def chat(
    provider: str, key: str, model: str, messages: list,
    temperature: float = 0.4, max_tokens: int = 1200,
) -> tuple[str, int | None, int | None]:
    """Returns (text, tokens_in, tokens_out)."""
    if provider == "groq":
        data = await _post_json(
            "https://api.groq.com/openai/v1/chat/completions",
            {"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
            _openai_shape_chat(model, messages, temperature, max_tokens),
        )
        usage = data.get("usage", {}) or {}
        text = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
        return strip_think(text), usage.get("prompt_tokens"), usage.get("completion_tokens")
    if provider == "openai":
        data = await _post_json(
            "https://api.openai.com/v1/chat/completions",
            {"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
            _openai_shape_chat(model, messages, temperature, max_tokens),
        )
        usage = data.get("usage", {}) or {}
        text = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
        return strip_think(text), usage.get("prompt_tokens"), usage.get("completion_tokens")
    if provider == "gemini":
        contents, system = _gemini_contents(messages)
        payload: dict = {
            "contents": contents,
            "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
        }
        if system:
            payload["systemInstruction"] = system
        data = await _post_json(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}",
            {"Content-Type": "application/json"},
            payload,
        )
        text = ""
        try:
            parts = data["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts)
        except (KeyError, IndexError, TypeError):
            text = ""
        usage = data.get("usageMetadata", {}) or {}
        return strip_think(text), usage.get("promptTokenCount"), usage.get("candidatesTokenCount")
    if provider == "claude":
        system = ""
        claude_msgs = []
        for m in messages:
            if m.get("role") == "system":
                c = m.get("content", "")
                system += (c if isinstance(c, str) else str(c)) + "\n"
            else:
                claude_msgs.append({"role": m.get("role", "user"), "content": m.get("content", "")})
        data = await _post_json(
            "https://api.anthropic.com/v1/messages",
            {
                "Content-Type": "application/json",
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
            },
            {
                "model": model,
                "max_tokens": max_tokens,
                "system": system.strip(),
                "messages": claude_msgs,
            },
        )
        text = ""
        try:
            text = "".join(
                b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"
            )
        except (KeyError, TypeError):
            text = ""
        usage = data.get("usage", {}) or {}
        return strip_think(text), usage.get("input_tokens"), usage.get("output_tokens")
    raise ProviderError(f"Unknown provider: {provider}")


# --------------------------------------------------------------- vision ----
def _parse_data_url(image: str) -> tuple[str, str]:
    """Split 'data:<mime>;base64,<data>' -> (mime, base64)."""
    if image.startswith("data:"):
        header, _, b64 = image.partition(",")
        mime = header.split(";")[0].replace("data:", "") or "image/jpeg"
        return mime, b64
    return "image/jpeg", image


async def vision(
    provider: str, key: str, model: str, image: str, prompt: str | None = None,
) -> tuple[str, int | None, int | None]:
    prompt = prompt or VISION_PROMPT
    if provider in ("groq", "openai"):
        url = (
            "https://api.groq.com/openai/v1/chat/completions"
            if provider == "groq"
            else "https://api.openai.com/v1/chat/completions"
        )
        data = await _post_json(
            url,
            {"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
            {
                "model": model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": image}},
                        ],
                    }
                ],
                "temperature": 0.2,
                "max_tokens": 1000,
            },
        )
        usage = data.get("usage", {}) or {}
        text = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
        return strip_think(text), usage.get("prompt_tokens"), usage.get("completion_tokens")
    if provider == "gemini":
        mime, b64 = _parse_data_url(image)
        data = await _post_json(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}",
            {"Content-Type": "application/json"},
            {
                "contents": [
                    {
                        "parts": [
                            {"text": prompt},
                            {"inlineData": {"mimeType": mime, "data": b64}},
                        ]
                    }
                ],
                "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1000},
            },
        )
        text = ""
        try:
            parts = data["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts)
        except (KeyError, IndexError, TypeError):
            text = ""
        usage = data.get("usageMetadata", {}) or {}
        return strip_think(text), usage.get("promptTokenCount"), usage.get("candidatesTokenCount")
    if provider == "claude":
        mime, b64 = _parse_data_url(image)
        data = await _post_json(
            "https://api.anthropic.com/v1/messages",
            {
                "Content-Type": "application/json",
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
            },
            {
                "model": model,
                "max_tokens": 1000,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {"type": "base64", "media_type": mime, "data": b64},
                            },
                            {"type": "text", "text": prompt},
                        ],
                    }
                ],
            },
        )
        text = ""
        try:
            text = "".join(
                b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"
            )
        except (KeyError, TypeError):
            text = ""
        usage = data.get("usage", {}) or {}
        return strip_think(text), usage.get("input_tokens"), usage.get("output_tokens")
    raise ProviderError(f"Unknown provider: {provider}")


# ----------------------------------------------------------- transcribe ----
async def transcribe(
    groq_key: str | None, openai_key: str | None,
    audio_bytes: bytes, filename: str, content_type: str,
) -> str:
    """Whisper via Groq first, else OpenAI. Raises ProviderError if neither
    key is configured."""
    if groq_key:
        data = await _post_multipart(
            "https://api.groq.com/openai/v1/audio/transcriptions",
            {"Authorization": f"Bearer {groq_key}"},
            {"file": (filename, audio_bytes, content_type or "audio/webm")},
            {"model": "whisper-large-v3-turbo"},
        )
        return (data.get("text") or "").strip()
    if openai_key:
        data = await _post_multipart(
            "https://api.openai.com/v1/audio/transcriptions",
            {"Authorization": f"Bearer {openai_key}"},
            {"file": (filename, audio_bytes, content_type or "audio/webm")},
            {"model": "whisper-1"},
        )
        return (data.get("text") or "").strip()
    raise ProviderError("NO_PROVIDER_KEY")
