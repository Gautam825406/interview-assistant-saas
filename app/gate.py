"""Plan gate: who may use AI / start sessions / start mocks.

Paid = user has a subscription with status active and expires_at in the
future. Free = lifetime caps from the free plan (10 sessions, 1 mock).
"""
from fastapi import HTTPException
from sqlalchemy.orm import Session

from .db import utcnow
from .models import Plan, Subscription, User


def get_plan(db: Session, slug: str) -> Plan | None:
    return db.query(Plan).filter(Plan.slug == slug).first()


def active_subscription(db: Session, user_id: int) -> Subscription | None:
    now = utcnow()
    sub = (
        db.query(Subscription)
        .filter(
            Subscription.user_id == user_id,
            Subscription.status == "active",
            Subscription.expires_at.isnot(None),
            Subscription.expires_at > now,
        )
        .order_by(Subscription.expires_at.desc())
        .first()
    )
    return sub


def is_paid(db: Session, user: User) -> bool:
    return active_subscription(db, user.id) is not None


def check_ai_gate(db: Session, user: User) -> None:
    """Gate for /api/ai/* calls inside a live session. Paid: unlimited.
    Free: allowed while sessions_used < free plan's sessions_limit.
    Raises 402 PLAN_LIMIT when the free cap is hit."""
    if is_paid(db, user):
        return
    plan = get_plan(db, "free")
    limit = plan.sessions_limit if plan else 10
    if limit is not None and user.sessions_used >= limit:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "PLAN_LIMIT",
                "message": "You have used all 10 free sessions. Upgrade to a paid plan to continue.",
            },
        )


def check_session_start(db: Session, user: User) -> None:
    """Gate for /api/sessions/start: free users may start a session only
    while under the cap; starting consumes one session."""
    if is_paid(db, user):
        return
    plan = get_plan(db, "free")
    limit = plan.sessions_limit if plan else 10
    if limit is not None and user.sessions_used >= limit:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "PLAN_LIMIT",
                "message": "You have used all 10 free sessions. Upgrade to a paid plan to continue.",
            },
        )


def check_mock_start(db: Session, user: User) -> None:
    if is_paid(db, user):
        return
    plan = get_plan(db, "free")
    limit = plan.mock_limit if plan else 1
    if limit is not None and user.mocks_used >= limit:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "PLAN_LIMIT",
                "message": "You have used your 1 free mock interview. Upgrade to a paid plan to continue.",
            },
        )
