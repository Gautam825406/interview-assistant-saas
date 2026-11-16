"""Seed default plans on startup (only if the plans table is empty)."""
from sqlalchemy.orm import Session

from .models import Plan

DEFAULT_PLANS = [
    {
        "slug": "free",
        "name": "Free",
        "price": 0.0,
        "currency": "USD",
        "duration_days": 0,
        "sessions_limit": 10,
        "minutes_per_session": 10,
        "mock_limit": 1,
        "features": ["10 live sessions", "10 minutes per session", "1 mock interview"],
        "sort_order": 1,
    },
    {
        "slug": "weekly",
        "name": "Weekly",
        "price": 78.0,
        "currency": "USD",
        "duration_days": 7,
        "sessions_limit": None,
        "minutes_per_session": None,
        "mock_limit": None,
        "features": ["Unlimited live sessions", "Unlimited mock interviews", "Resume PDFs"],
        "sort_order": 2,
    },
    {
        "slug": "monthly",
        "name": "Monthly",
        "price": 149.90,
        "currency": "USD",
        "duration_days": 30,
        "sessions_limit": None,
        "minutes_per_session": None,
        "mock_limit": None,
        "features": ["Unlimited live sessions", "Unlimited mock interviews", "Resume PDFs", "Headshots"],
        "sort_order": 3,
    },
    {
        "slug": "yearly",
        "name": "Yearly",
        "price": 599.90,
        "currency": "USD",
        "duration_days": 365,
        "sessions_limit": None,
        "minutes_per_session": None,
        "mock_limit": None,
        "features": [
            "Unlimited live sessions",
            "Unlimited mock interviews",
            "Resume PDFs",
            "Headshots",
            "$49.99/mo billed yearly",
        ],
        "sort_order": 4,
    },
]


def seed_plans(db: Session) -> None:
    if db.query(Plan).count() > 0:
        return
    for p in DEFAULT_PLANS:
        db.add(Plan(**p))
    db.commit()
