"""Webhook: HMAC signature check + idempotent activation.
A replayed webhook must never double-activate or duplicate a subscription.
"""
import base64
import hashlib
import hmac
import json

import pytest

import app.routers.subscriptions as subs
import app.routers.webhooks as webhooks
from app.models import Payment, Subscription
from tests.conftest import TestingSessionLocal, auth


@pytest.fixture()
def mock_cashfree(monkeypatch):
    async def fake_create_order(**kwargs):
        return {
            "order_id": kwargs["order_id"],
            "payment_session_id": "sess_test_123",
            "cf_order_id": kwargs["order_id"],
        }

    monkeypatch.setattr(subs.cashfree, "create_order", fake_create_order)


def _sign(body: bytes, timestamp: str, secret: str = "test-secret-key") -> str:
    digest = hmac.new(secret.encode(), timestamp.encode() + body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def _webhook_body(order_id: str) -> dict:
    return {
        "type": "PAYMENT_SUCCESS_WEBHOOK",
        "data": {
            "order": {"order_id": order_id},
            "payment": {"cf_payment_id": "cfpay_1", "payment_status": "SUCCESS"},
        },
    }


def test_webhook_activates_and_is_idempotent(client, user, mock_cashfree, db, monkeypatch):
    monkeypatch.setattr(webhooks, "SessionLocal", TestingSessionLocal)
    r = client.post(
        "/api/subscriptions/checkout",
        json={"plan_slug": "monthly"},
        headers=auth(user["token"]),
    )
    order_id = r.json()["cf_order_id"]

    body = json.dumps(_webhook_body(order_id)).encode()
    ts = "2026-11-16T07:00:00Z"
    headers = {"x-webhook-signature": _sign(body, ts), "x-webhook-timestamp": ts}

    r = client.post("/api/webhooks/cashfree", content=body, headers=headers)
    assert r.status_code == 200
    pay = db.query(Payment).filter(Payment.cf_order_id == order_id).first()
    assert pay.status == "success"
    assert pay.cf_payment_id == "cfpay_1"
    assert db.query(Subscription).filter(Subscription.user_id == user["user"]["id"]).count() == 1

    # Replay the exact same webhook — still one subscription, still success.
    r = client.post("/api/webhooks/cashfree", content=body, headers=headers)
    assert r.status_code == 200
    assert db.query(Subscription).filter(Subscription.user_id == user["user"]["id"]).count() == 1
    assert db.query(Payment).filter(Payment.cf_order_id == order_id).count() == 1

    # User is now on the paid plan.
    r = client.get("/api/auth/me", headers=auth(user["token"]))
    assert r.json()["user"]["plan_slug"] == "monthly"


def test_webhook_bad_signature_ignored(client, user, mock_cashfree, db, monkeypatch):
    monkeypatch.setattr(webhooks, "SessionLocal", TestingSessionLocal)
    r = client.post(
        "/api/subscriptions/checkout",
        json={"plan_slug": "monthly"},
        headers=auth(user["token"]),
    )
    order_id = r.json()["cf_order_id"]
    body = json.dumps(_webhook_body(order_id)).encode()
    headers = {
        "x-webhook-signature": _sign(body, "2026-11-16T07:00:00Z", secret="wrong-secret"),
        "x-webhook-timestamp": "2026-11-16T07:00:00Z",
    }
    r = client.post("/api/webhooks/cashfree", content=body, headers=headers)
    assert r.status_code == 200  # never leak internals
    pay = db.query(Payment).filter(Payment.cf_order_id == order_id).first()
    assert pay.status == "pending"  # not activated
    assert db.query(Subscription).filter(Subscription.user_id == user["user"]["id"]).count() == 0


def test_webhook_non_success_event_ignored(client, user, mock_cashfree, db, monkeypatch):
    monkeypatch.setattr(webhooks, "SessionLocal", TestingSessionLocal)
    r = client.post(
        "/api/subscriptions/checkout",
        json={"plan_slug": "monthly"},
        headers=auth(user["token"]),
    )
    order_id = r.json()["cf_order_id"]
    payload = {"type": "PAYMENT_FAILED_WEBHOOK", "data": {"order": {"order_id": order_id}}}
    body = json.dumps(payload).encode()
    ts = "2026-11-16T07:00:00Z"
    headers = {"x-webhook-signature": _sign(body, ts), "x-webhook-timestamp": ts}
    r = client.post("/api/webhooks/cashfree", content=body, headers=headers)
    assert r.status_code == 200
    assert db.query(Subscription).filter(Subscription.user_id == user["user"]["id"]).count() == 0
