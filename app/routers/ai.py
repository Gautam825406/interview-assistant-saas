"""AI proxy: chat, vision, transcribe, status + session/mock start gates.

All AI calls are proxied with the OWNER's provider keys (from
provider_settings, Fernet-encrypted). End users never see keys.
Plan gate (402 PLAN_LIMIT) applies on every call.
"""
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import providers
from ..db import get_db
from ..deps import get_current_user
from ..gate import check_ai_gate, check_mock_start, check_session_start, get_plan, is_paid
from ..models import AIUsageLog, User
from ..security import decrypt_value
from ..settings_util import (
    chat_model,
    get_provider_settings,
    provider_key,
    vision_model,
)

router = APIRouter(prefix="/api/ai", tags=["ai"])

# Session/mock start live at /api/sessions/start and /api/mocks/start
# (contract paths — NOT under /api/ai).
session_router = APIRouter(prefix="/api", tags=["sessions"])


class ChatIn(BaseModel):
    messages: list
    temperature: float | None = 0.4
    max_tokens: int | None = 1200


class VisionIn(BaseModel):
    image: str
    prompt: str | None = None


def _log(db: Session, user_id: int, endpoint: str, provider: str, model: str,
         ok: bool, error: str | None = None,
         tokens_in: int | None = None, tokens_out: int | None = None) -> None:
    try:
        db.add(AIUsageLog(
            user_id=user_id, endpoint=endpoint, provider=provider, model=model,
            tokens_in=tokens_in, tokens_out=tokens_out, ok=ok, error=error,
        ))
        db.commit()
    except Exception:
        db.rollback()


def _provider_or_503(db: Session):
    """Returns (settings_row, provider, key, chat_m, vision_m) or raises 503."""
    row = get_provider_settings(db)
    provider = row.default_provider or "groq"
    key = provider_key(row, provider)
    if not key:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "NO_PROVIDER_KEY",
                "message": "The service owner has not added an AI key yet.",
            },
        )
    return row, provider, key, chat_model(row, provider), vision_model(row, provider)


@session_router.post("/sessions/start")
def sessions_start(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    check_session_start(db, user)
    if not is_paid(db, user):
        user.sessions_used += 1
        db.commit()
    plan = get_plan(db, "free")
    return {
        "ok": True,
        "sessions_used": user.sessions_used,
        "sessions_limit": plan.sessions_limit if plan else 10,
    }


@session_router.post("/mocks/start")
def mocks_start(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    check_mock_start(db, user)
    if not is_paid(db, user):
        user.mocks_used += 1
        db.commit()
    plan = get_plan(db, "free")
    return {
        "ok": True,
        "mocks_used": user.mocks_used,
        "mock_limit": plan.mock_limit if plan else 1,
    }


@router.post("/chat")
async def chat(body: ChatIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    check_ai_gate(db, user)
    row, provider, key, model, _vision = _provider_or_503(db)
    if not body.messages:
        raise HTTPException(status_code=400, detail="messages is required")
    try:
        text, t_in, t_out = await providers.chat(
            provider, key, model, body.messages,
            temperature=body.temperature or 0.4,
            max_tokens=body.max_tokens or 1200,
        )
    except providers.ProviderError as e:
        _log(db, user.id, "chat", provider, model, False, str(e))
        return JSONResponse(status_code=502, content={"error": str(e) or "AI provider error"})
    _log(db, user.id, "chat", provider, model, True, tokens_in=t_in, tokens_out=t_out)
    return {"text": text, "provider": provider, "model": model}


@router.post("/vision")
async def vision(body: VisionIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    check_ai_gate(db, user)
    row, provider, key, _chat, vmodel = _provider_or_503(db)
    if not body.image:
        raise HTTPException(status_code=400, detail="image is required")
    try:
        text, t_in, t_out = await providers.vision(provider, key, vmodel, body.image, body.prompt)
    except providers.ProviderError as e:
        _log(db, user.id, "vision", provider, vmodel, False, str(e))
        return JSONResponse(status_code=502, content={"error": str(e) or "AI provider error"})
    _log(db, user.id, "vision", provider, vmodel, True, tokens_in=t_in, tokens_out=t_out)
    return {"text": text, "provider": provider, "model": vmodel}


@router.post("/transcribe")
async def transcribe(
    audio: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    check_ai_gate(db, user)
    row = get_provider_settings(db)
    groq_key = provider_key(row, "groq")
    openai_key = provider_key(row, "openai")
    if not groq_key and not openai_key:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "NO_PROVIDER_KEY",
                "message": "The service owner has not added an AI key yet.",
            },
        )
    data = await audio.read()
    provider = "groq" if groq_key else "openai"
    try:
        text = await providers.transcribe(
            groq_key, openai_key, data, audio.filename or "chunk.webm",
            audio.content_type or "audio/webm",
        )
    except providers.ProviderError as e:
        _log(db, user.id, "transcribe", provider, "whisper", False, str(e))
        return JSONResponse(status_code=502, content={"error": str(e) or "Transcription failed"})
    _log(db, user.id, "transcribe", provider, "whisper", True)
    return {"text": text}


@router.get("/status")
def status(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = get_provider_settings(db)
    provider = row.default_provider or "groq"
    key = provider_key(row, provider)
    return {
        "provider": provider,
        "configured": bool(key),
        "chat_model": chat_model(row, provider),
        "vision_model": vision_model(row, provider),
    }
