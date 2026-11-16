"""Billing: idempotent subscription activation shared by the verify
endpoint and the Cashfree webhook. A replay of either must never
double-activate or create a duplicate subscription/payment.
"""
from datetime import timedelta

from sqlalchemy.orm import Session

from .db import utcnow
from .models import Payment, Plan, Subscription, User


def activate_order(
    db: Session, payment: Payment, cf_payment_id: str | None = None
) -> Subscription | None:
    """Mark a pending payment as success and create/extend the subscription.
    If the payment is already success, return the existing subscription
    (idempotent — safe to call again on webhook/verify replay)."""
    if payment.status == "success":
        existing = (
            db.query(Subscription)
            .filter(Subscription.cf_order_id == payment.cf_order_id)
            .order_by(Subscription.id.desc())
            .first()
        )
        if existing:
            return existing
        # Payment marked success but no subscription (should not happen) —
        # fall through and create one.
    plan = db.query(Plan).filter(Plan.slug == payment.plan_slug).first()
    if not plan:
        return None
    user = db.get(User, payment.user_id)
    if not user:
        return None

    now = utcnow()
    duration = plan.duration_days or 0
    # Extend an existing active subscription for the same plan, else start now.
    current = (
        db.query(Subscription)
        .filter(
            Subscription.user_id == user.id,
            Subscription.plan_slug == plan.slug,
            Subscription.status == "active",
            Subscription.expires_at.isnot(None),
            Subscription.expires_at > now,
        )
        .order_by(Subscription.expires_at.desc())
        .first()
    )
    starts_at = current.expires_at if current else now
    expires_at = starts_at + timedelta(days=duration) if duration else None

    sub = Subscription(
        user_id=user.id,
        plan_slug=plan.slug,
        status="active",
        starts_at=starts_at,
        expires_at=expires_at,
        cf_order_id=payment.cf_order_id,
        amount=payment.amount,
        currency=payment.currency,
    )
    db.add(sub)
    payment.status = "success"
    if cf_payment_id:
        payment.cf_payment_id = cf_payment_id
    user.plan_slug = plan.slug
    db.commit()
    db.refresh(sub)
    return sub
