"""Shared helpers: provider-settings row, key/model lookup, serializers."""
from sqlalchemy.orm import Session

from .models import Plan, ProviderSettings, Subscription, User
from .security import decrypt_value, mask_key

PROVIDERS = ("groq", "openai", "gemini", "claude")

KEY_ATTRS = {
    "groq": "groq_key_enc",
    "openai": "openai_key_enc",
    "gemini": "gemini_key_enc",
    "claude": "claude_key_enc",
}
CHAT_MODEL_ATTRS = {
    "groq": "groq_model",
    "openai": "openai_model",
    "gemini": "gemini_model",
    "claude": "claude_model",
}
VISION_MODEL_ATTRS = {
    "groq": "groq_vision_model",
    "openai": "openai_vision_model",
    "gemini": "gemini_vision_model",
    "claude": "claude_vision_model",
}


def get_provider_settings(db: Session) -> ProviderSettings:
    row = db.get(ProviderSettings, 1)
    if not row:
        row = ProviderSettings(id=1)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def provider_key(row: ProviderSettings, provider: str) -> str | None:
    return decrypt_value(getattr(row, KEY_ATTRS[provider], None))


def chat_model(row: ProviderSettings, provider: str) -> str:
    return getattr(row, CHAT_MODEL_ATTRS[provider])


def vision_model(row: ProviderSettings, provider: str) -> str:
    return getattr(row, VISION_MODEL_ATTRS[provider])


def keys_masked(row: ProviderSettings) -> dict:
    return {
        p: mask_key(provider_key(row, p)) for p in PROVIDERS
    }


def user_dict(u: User) -> dict:
    return {
        "id": u.id,
        "name": u.name,
        "email": u.email,
        "role": u.role,
        "plan_slug": u.plan_slug,
    }


def plan_dict(p: Plan, public: bool = True) -> dict:
    d = {
        "slug": p.slug,
        "name": p.name,
        "price": p.price,
        "currency": p.currency,
        "duration_days": p.duration_days,
        "sessions_limit": p.sessions_limit,
        "minutes_per_session": p.minutes_per_session,
        "mock_limit": p.mock_limit,
        "features": p.features or [],
    }
    if not public:
        d.update({"id": p.id, "active": p.active, "sort_order": p.sort_order})
    return d


def subscription_dict(s: Subscription | None) -> dict | None:
    if not s:
        return None
    return {
        "id": s.id,
        "plan_slug": s.plan_slug,
        "status": s.status,
        "starts_at": s.starts_at.isoformat() if s.starts_at else None,
        "expires_at": s.expires_at.isoformat() if s.expires_at else None,
        "amount": s.amount,
        "currency": s.currency,
    }
