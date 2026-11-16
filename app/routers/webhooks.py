"""Cashfree webhook — no auth; HMAC signature check over raw body.
Always returns 200 (never leak internals). Idempotent activation via
billing.activate_order: a replay never double-activates.
"""
import json

from fastapi import APIRouter, Request
from sqlalchemy.orm import Session

from .. import cashfree
from ..billing import activate_order
from ..db import SessionLocal
from ..models import Payment

router = APIRouter(tags=["webhooks"])


def _extract_order_id(payload: dict) -> str | None:
    data = payload.get("data") or {}
    order = data.get("order") or {}
    return (
        order.get("order_id")
        or data.get("order_id")
        or payload.get("order_id")
        or payload.get("cf_order_id")
    )


def _extract_payment_id(payload: dict) -> str | None:
    data = payload.get("data") or {}
    payment = data.get("payment") or {}
    return payment.get("cf_payment_id") or data.get("cf_payment_id")


def _is_payment_success(payload: dict) -> bool:
    event = (payload.get("type") or payload.get("event") or "").upper()
    if "PAYMENT_SUCCESS" in event:
        return True
    data = payload.get("data") or {}
    payment = data.get("payment") or {}
    status = (payment.get("payment_status") or data.get("payment_status") or "").upper()
    return status == "SUCCESS"


@router.post("/api/webhooks/cashfree")
async def cashfree_webhook(request: Request):
    raw = await request.body()
    signature = request.headers.get("x-webhook-signature", "")
    timestamp = request.headers.get("x-webhook-timestamp", "")
    if not cashfree.verify_webhook_signature(raw, timestamp, signature):
        return {"ok": True}
    try:
        payload = json.loads(raw.decode() or "{}")
    except Exception:
        return {"ok": True}
    if not _is_payment_success(payload):
        return {"ok": True}
    order_id = _extract_order_id(payload)
    if not order_id:
        return {"ok": True}
    db: Session = SessionLocal()
    try:
        payment = db.query(Payment).filter(Payment.cf_order_id == order_id).first()
        if payment and payment.status != "success":
            activate_order(db, payment, _extract_payment_id(payload))
    finally:
        db.close()
    return {"ok": True}
