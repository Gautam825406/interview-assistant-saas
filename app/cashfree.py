"""Cashfree PG client (orders API v2023-08-01) + webhook signature check.

Cashfree webhook signature: HMAC-SHA256 over (timestamp + raw body) with the
secret key, base64-encoded, sent as `x-webhook-signature` with
`x-webhook-timestamp`. A dotted variant (timestamp + "." + body) is also
accepted as a fallback. Never log or return key values.
"""
import base64
import hashlib
import hmac
import uuid

import httpx

from .config import settings

API_VERSION = "2023-08-01"


def base_url() -> str:
    return (
        "https://api.cashfree.com"
        if settings.cashfree_env == "PROD"
        else "https://sandbox.cashfree.com"
    )


def is_configured() -> bool:
    return bool(settings.cashfree_app_id and settings.cashfree_secret_key)


def new_order_id() -> str:
    return "IA" + uuid.uuid4().hex[:20].upper()


def _headers() -> dict:
    return {
        "x-api-version": API_VERSION,
        "x-client-id": settings.cashfree_app_id,
        "x-client-secret": settings.cashfree_secret_key,
        "Content-Type": "application/json",
    }


async def create_order(
    order_id: str,
    amount: float,
    currency: str,
    customer_id: str,
    customer_email: str,
    customer_phone: str,
) -> dict:
    """Create a Cashfree order. Returns the raw JSON (payment_session_id etc.).

    customer_phone is required by Cashfree — an order without it fails
    with 400 "customer_phone is missing in the request".
    """
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{base_url()}/pg/orders",
            headers=_headers(),
            json={
                "order_id": order_id,
                "order_amount": amount,
                "order_currency": currency,
                "customer_details": {
                    "customer_id": customer_id,
                    "customer_email": customer_email,
                    "customer_phone": customer_phone,
                },
            },
        )
    if resp.status_code >= 400:
        try:
            msg = resp.json().get("message", resp.text)
        except Exception:
            msg = resp.text
        raise RuntimeError(f"Cashfree order failed ({resp.status_code}): {msg}")
    return resp.json()


async def get_order(order_id: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{base_url()}/pg/orders/{order_id}", headers=_headers())
    if resp.status_code >= 400:
        try:
            msg = resp.json().get("message", resp.text)
        except Exception:
            msg = resp.text
        raise RuntimeError(f"Cashfree order fetch failed ({resp.status_code}): {msg}")
    return resp.json()


def verify_webhook_signature(raw_body: bytes, timestamp: str, signature: str) -> bool:
    """Check the Cashfree webhook HMAC signature. Returns False on any
    mismatch / missing values — callers must not leak why."""
    if not raw_body or not timestamp or not signature:
        return False
    secret = settings.cashfree_secret_key.encode()
    for payload in (timestamp.encode() + raw_body, (timestamp + ".").encode() + raw_body):
        digest = hmac.new(secret, payload, hashlib.sha256).digest()
        expected = base64.b64encode(digest).decode()
        if hmac.compare_digest(expected, signature):
            return True
    return False
