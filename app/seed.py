"""Seed default plans on startup (only if the plans table is empty).

Prices are in INR. Also converts the original USD seed prices to INR
once (Nov 2026): plans that still carry the untouched USD seed values
get the matching INR price; anything the admin customised is left alone.
The currency may be "USD" (original seed) or "₹" (typed into the Admin
panel instead of the "INR" code) — both mean the same legacy state.
"""
from sqlalchemy.orm import Session

from .models import Plan

# INR prices (converted from the original USD prices at ~Rs 85/$,
# rounded to clean numbers): free Rs 0, weekly Rs 6,499, monthly
# Rs 12,999, yearly Rs 49,999 (Rs 4,167/mo billed yearly).
DEFAULT_PLANS = [
    {
        "slug": "free",
        "name": "Free",
        "price": 0.0,
        "currency": "INR",
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
        "price": 6499.0,
        "currency": "INR",
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
        "price": 12999.0,
        "currency": "INR",
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
        "price": 49999.0,
        "currency": "INR",
        "duration_days": 365,
        "sessions_limit": None,
        "minutes_per_session": None,
        "mock_limit": None,
        "features": [
            "Unlimited live sessions",
            "Unlimited mock interviews",
            "Resume PDFs",
            "Headshots",
            "₹4,167/mo billed yearly",
        ],
        "sort_order": 4,
    },
]

# The original USD seed prices (pre-INR). A plan is only converted when
# its price still equals its USD seed value exactly — a customised price
# is never overwritten.
OLD_USD_PRICES = {"free": 0.0, "weekly": 78.0, "monthly": 149.90, "yearly": 599.90}


def migrate_usd_plans_to_inr(db: Session) -> None:
    changed = False
    for p in DEFAULT_PLANS:
        row = db.query(Plan).filter(Plan.slug == p["slug"]).first()
        if not row:
            continue
        # Currency "USD" is the original seed; "₹" is what lands in the
        # column when the Admin panel's currency box is filled with the
        # rupee symbol instead of the "INR" code. Either way, if the price
        # is still the untouched USD seed value, convert the row.
        if row.currency in ("USD", "₹") and float(row.price or 0) == OLD_USD_PRICES.get(p["slug"]):
            row.price = p["price"]
            row.currency = "INR"
            changed = True
        # The yearly plan's feature line still quotes the old dollar price.
        if row.slug == "yearly" and row.features and "$49.99/mo billed yearly" in row.features:
            row.features = ["₹4,167/mo billed yearly" if f == "$49.99/mo billed yearly" else f for f in row.features]
            changed = True
    if changed:
        db.commit()


def seed_plans(db: Session) -> None:
    if db.query(Plan).count() == 0:
        for p in DEFAULT_PLANS:
            db.add(Plan(**p))
        db.commit()
        return
    migrate_usd_plans_to_inr(db)
