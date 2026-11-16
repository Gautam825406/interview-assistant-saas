"""Seed migration: original USD prices — and plans whose currency was
typed as the ₹ symbol in the Admin panel — convert to INR once."""
from app.models import Plan
from app.seed import seed_plans


def test_migrates_usd_and_rupee_symbol_plans_to_inr(db):
    # Simulate the live DB before the INR switch: monthly still USD,
    # the other plans had their currency typed as "₹" in the Admin panel
    # while their prices were left at the USD values.
    legacy = {"free": (0.0, "₹"), "weekly": (78.0, "₹"), "monthly": (149.90, "USD"), "yearly": (599.90, "₹")}
    for slug, (price, currency) in legacy.items():
        row = db.query(Plan).filter(Plan.slug == slug).first()
        row.price = price
        row.currency = currency
        if slug == "yearly":
            row.features = ["Unlimited live sessions", "$49.99/mo billed yearly"]
    db.commit()
    seed_plans(db)
    rows = {p.slug: p for p in db.query(Plan).all()}
    assert rows["free"].price == 0.0 and rows["free"].currency == "INR"
    assert rows["weekly"].price == 6499.0 and rows["weekly"].currency == "INR"
    assert rows["monthly"].price == 12999.0 and rows["monthly"].currency == "INR"
    assert rows["yearly"].price == 49999.0 and rows["yearly"].currency == "INR"
    assert "₹4,167/mo billed yearly" in rows["yearly"].features
    assert "$49.99/mo billed yearly" not in rows["yearly"].features
    # Second run is a no-op.
    seed_plans(db)
    assert db.query(Plan).count() == 4


def test_customised_price_is_never_converted(db):
    row = db.query(Plan).filter(Plan.slug == "monthly").first()
    row.price = 999.0
    row.currency = "USD"
    db.commit()
    seed_plans(db)
    row = db.query(Plan).filter(Plan.slug == "monthly").first()
    assert row.price == 999.0 and row.currency == "USD"
