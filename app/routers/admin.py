"""Admin endpoints (Bearer + role admin only, 403 otherwise):
overview, users, grant, subscriptions, payments, providers, plans.
Provider keys are never returned full — masked (last 4) only.
"""
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..db import get_db, utcnow
from ..deps import require_admin
from ..gate import active_subscription
from ..models import AIUsageLog, Payment, Plan, ProviderSettings, Subscription, User
from ..security import encrypt_value
from ..settings_util import (
    CHAT_MODEL_ATTRS,
    KEY_ATTRS,
    PROVIDERS,
    VISION_MODEL_ATTRS,
    get_provider_settings,
    keys_masked,
    plan_dict,
    subscription_dict,
    user_dict,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])


# ------------------------------------------------------------- overview ----
@router.get("/overview")
def overview(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    users_total = db.query(User).count()
    paying = (
        db.query(Subscription.user_id)
        .filter(Subscription.status == "active", Subscription.expires_at > utcnow())
        .distinct()
        .count()
    )
    active_subs = (
        db.query(Subscription)
        .filter(Subscription.status == "active", Subscription.expires_at > utcnow())
        .count()
    )
    revenue = (
        db.query(func.coalesce(func.sum(Payment.amount), 0.0))
        .filter(Payment.status == "success")
        .scalar()
    )
    today = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    ai_calls_today = (
        db.query(AIUsageLog).filter(AIUsageLog.created_at >= today).count()
    )
    return {
        "users_total": users_total,
        "paying_users": paying,
        "active_subscriptions": active_subs,
        "revenue_total": float(revenue or 0.0),
        "ai_calls_today": ai_calls_today,
        "free_users": users_total - paying,
    }


# ---------------------------------------------------------------- users ----
@router.get("/users")
def list_users(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    users = db.query(User).order_by(User.created_at.desc()).all()
    out = []
    for u in users:
        d = user_dict(u)
        d["created_at"] = u.created_at.isoformat() if u.created_at else None
        d["sessions_used"] = u.sessions_used
        d["mocks_used"] = u.mocks_used
        d["subscription"] = subscription_dict(active_subscription(db, u.id))
        out.append(d)
    return out


class PatchUserIn(BaseModel):
    role: str | None = None


@router.patch("/users/{user_id}")
def patch_user(user_id: int, body: PatchUserIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if body.role is not None:
        if body.role not in ("admin", "user"):
            raise HTTPException(status_code=400, detail="role must be admin or user")
        target.role = body.role
    db.commit()
    return user_dict(target)


class GrantIn(BaseModel):
    plan_slug: str
    days: int | None = None


@router.post("/users/{user_id}/grant")
def grant(user_id: int, body: GrantIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    plan = db.query(Plan).filter(Plan.slug == body.plan_slug).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    now = utcnow()
    days = body.days if body.days is not None else (plan.duration_days or 0)
    # Extend an existing active subscription for the same plan.
    current = active_subscription(db, target.id)
    starts_at = current.expires_at if (current and current.plan_slug == plan.slug) else now
    expires_at = starts_at + timedelta(days=days) if days else None
    sub = Subscription(
        user_id=target.id,
        plan_slug=plan.slug,
        status="active",
        starts_at=starts_at,
        expires_at=expires_at,
        cf_order_id=None,
        amount=0.0,
        currency=plan.currency,
    )
    db.add(sub)
    target.plan_slug = plan.slug
    db.commit()
    db.refresh(sub)
    return {"subscription": subscription_dict(sub)}


# -------------------------------------------------- subscriptions/payments --
@router.get("/subscriptions")
def list_subscriptions(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    subs = db.query(Subscription).order_by(Subscription.id.desc()).all()
    out = []
    for s in subs:
        d = subscription_dict(s)
        u = db.get(User, s.user_id)
        d["user_email"] = u.email if u else None
        d["user_name"] = u.name if u else None
        out.append(d)
    return out


@router.get("/payments")
def list_payments(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    pays = db.query(Payment).order_by(Payment.id.desc()).all()
    out = []
    for p in pays:
        u = db.get(User, p.user_id)
        out.append({
            "id": p.id,
            "user_email": u.email if u else None,
            "cf_order_id": p.cf_order_id,
            "plan_slug": p.plan_slug,
            "amount": p.amount,
            "currency": p.currency,
            "status": p.status,
            "cf_payment_id": p.cf_payment_id,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        })
    return out


# -------------------------------------------------------------- providers --
@router.get("/providers")
def get_providers(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    row = get_provider_settings(db)
    return {
        "default_provider": row.default_provider,
        "models": {
            "chat": {p: getattr(row, CHAT_MODEL_ATTRS[p]) for p in PROVIDERS},
            "vision": {p: getattr(row, VISION_MODEL_ATTRS[p]) for p in PROVIDERS},
        },
        "keys_masked": keys_masked(row),
    }


class PutProvidersIn(BaseModel):
    default_provider: str | None = None
    groq_key: str | None = None
    openai_key: str | None = None
    gemini_key: str | None = None
    claude_key: str | None = None
    groq_model: str | None = None
    openai_model: str | None = None
    gemini_model: str | None = None
    claude_model: str | None = None
    groq_vision_model: str | None = None
    openai_vision_model: str | None = None
    gemini_vision_model: str | None = None
    claude_vision_model: str | None = None


@router.put("/providers")
def put_providers(body: PutProvidersIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    row = get_provider_settings(db)
    if body.default_provider is not None:
        if body.default_provider not in PROVIDERS:
            raise HTTPException(status_code=400, detail="Invalid provider")
        row.default_provider = body.default_provider
    # Keys: empty string = leave unchanged; explicit null clears; else store encrypted.
    # Pydantic can't distinguish "absent" from "null" without a sentinel, so we
    # use model_fields_set: present-but-null clears, present-but-"" leaves as-is.
    data = body.model_dump()
    set_fields = body.model_fields_set
    for provider in PROVIDERS:
        field = f"{provider}_key"
        if field in set_fields:
            val = data[field]
            if val is None:
                setattr(row, KEY_ATTRS[provider], None)
            elif val != "":
                setattr(row, KEY_ATTRS[provider], encrypt_value(val))
    for attr in (
        "groq_model", "openai_model", "gemini_model", "claude_model",
        "groq_vision_model", "openai_vision_model", "gemini_vision_model", "claude_vision_model",
    ):
        if attr in set_fields and data[attr]:
            setattr(row, attr, data[attr])
    db.commit()
    db.refresh(row)
    return {
        "default_provider": row.default_provider,
        "models": {
            "chat": {p: getattr(row, CHAT_MODEL_ATTRS[p]) for p in PROVIDERS},
            "vision": {p: getattr(row, VISION_MODEL_ATTRS[p]) for p in PROVIDERS},
        },
        "keys_masked": keys_masked(row),
    }


# ------------------------------------------------------------------ plans --
@router.get("/plans")
def admin_plans(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    plans = db.query(Plan).order_by(Plan.sort_order, Plan.id).all()
    return [plan_dict(p, public=False) for p in plans]


class PlanIn(BaseModel):
    slug: str | None = None
    name: str | None = None
    price: float | None = None
    currency: str | None = None
    duration_days: int | None = None
    sessions_limit: int | None = None
    minutes_per_session: int | None = None
    mock_limit: int | None = None
    features: list | None = None
    active: bool | None = None
    sort_order: int | None = None


@router.post("/plans")
def create_plan(body: PlanIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    if not body.slug or not body.name:
        raise HTTPException(status_code=400, detail="slug and name are required")
    if db.query(Plan).filter(Plan.slug == body.slug).first():
        raise HTTPException(status_code=400, detail="A plan with this slug already exists")
    plan = Plan(
        slug=body.slug,
        name=body.name,
        price=body.price if body.price is not None else 0.0,
        currency=body.currency or "INR",
        duration_days=body.duration_days or 0,
        sessions_limit=body.sessions_limit,
        minutes_per_session=body.minutes_per_session,
        mock_limit=body.mock_limit,
        features=body.features or [],
        active=body.active if body.active is not None else True,
        sort_order=body.sort_order or 99,
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan_dict(plan, public=False)


@router.put("/plans/{slug}")
def update_plan(slug: str, body: PlanIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    plan = db.query(Plan).filter(Plan.slug == slug).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    data = body.model_dump()
    for field in (
        "name", "price", "currency", "duration_days", "sessions_limit",
        "minutes_per_session", "mock_limit", "features", "active", "sort_order",
    ):
        if field in body.model_fields_set:
            setattr(plan, field, data[field])
    db.commit()
    db.refresh(plan)
    return plan_dict(plan, public=False)
