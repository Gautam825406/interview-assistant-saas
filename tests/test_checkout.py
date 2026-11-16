"""Checkout: amount/currency always come from the DB plan, never the client.
Cashfree HTTP is mocked — no real calls."""
import pytest

import app.routers.subscriptions as subs
from tests.conftest import auth


@pytest.fixture()
def mock_cashfree(monkeypatch):
    captured = {}

    async def fake_create_order(**kwargs):
        captured.update(kwargs)
        return {
            "order_id": kwargs["order_id"],
            "payment_session_id": "sess_test_123",
            "cf_order_id": kwargs["order_id"],
        }

    async def fake_get_order(order_id):
        return {"order_id": order_id, "order_status": "PAID"}

    monkeypatch.setattr(subs.cashfree, "create_order", fake_create_order)
    monkeypatch.setattr(subs.cashfree, "get_order", fake_get_order)
    return captured


def test_checkout_uses_db_price(client, user, mock_cashfree):
    # Client sends ONLY the plan slug — there is no price field to tamper with.
    r = client.post(
        "/api/subscriptions/checkout",
        json={"plan_slug": "monthly"},
        headers=auth(user["token"]),
    )
    assert r.status_code == 200, r.text
    assert r.json()["payment_session_id"] == "sess_test_123"
    # The order amount is the DB plan price, not anything the client sent.
    assert mock_cashfree["amount"] == 12999.0
    assert mock_cashfree["currency"] == "INR"


def test_checkout_weekly_price(client, user, mock_cashfree):
    r = client.post(
        "/api/subscriptions/checkout",
        json={"plan_slug": "weekly"},
        headers=auth(user["token"]),
    )
    assert r.status_code == 200
    assert mock_cashfree["amount"] == 6499.0


def test_checkout_free_plan_400(client, user, mock_cashfree):
    r = client.post(
        "/api/subscriptions/checkout",
        json={"plan_slug": "free"},
        headers=auth(user["token"]),
    )
    assert r.status_code == 400


def test_checkout_unknown_plan_404(client, user, mock_cashfree):
    r = client.post(
        "/api/subscriptions/checkout",
        json={"plan_slug": "nope"},
        headers=auth(user["token"]),
    )
    assert r.status_code == 404


def test_checkout_requires_auth(client, mock_cashfree):
    r = client.post("/api/subscriptions/checkout", json={"plan_slug": "monthly"})
    assert r.status_code == 401


def test_verify_activates_on_paid(client, user, mock_cashfree, db):
    r = client.post(
        "/api/subscriptions/checkout",
        json={"plan_slug": "monthly"},
        headers=auth(user["token"]),
    )
    order_id = r.json()["cf_order_id"]
    r = client.get(
        f"/api/subscriptions/verify?order_id={order_id}",
        headers=auth(user["token"]),
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "success"
    assert r.json()["subscription"]["plan_slug"] == "monthly"
    # User plan updated + subscription active.
    r = client.get("/api/auth/me", headers=auth(user["token"]))
    assert r.json()["user"]["plan_slug"] == "monthly"
    assert r.json()["subscription"]["status"] == "active"
    # Verify again (replay) — still exactly one subscription.
    r = client.get(
        f"/api/subscriptions/verify?order_id={order_id}",
        headers=auth(user["token"]),
    )
    assert r.json()["status"] == "success"
    from app.models import Subscription

    assert db.query(Subscription).filter(Subscription.user_id == user["user"]["id"]).count() == 1
