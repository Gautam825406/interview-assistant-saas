"""Subscriptions: Cashfree checkout, verify, mine, cancel.

Amounts/currency ALWAYS come from the DB plan — never from the client.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import cashfree
from ..billing import activate_order
from ..config import settings
from ..db import get_db, utcnow
from ..deps import get_current_user
from ..gate import active_subscription
from ..models import Payment, Plan, Subscription, User
from ..phone import normalize_phone
from ..settings_util import subscription_dict

router = APIRouter(prefix="/api/subscriptions", tags=["subscriptions"])


class CheckoutIn(BaseModel):
    plan_slug: str


@router.post("/checkout")
async def checkout(body: CheckoutIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    plan = db.query(Plan).filter(Plan.slug == body.plan_slug, Plan.active.is_(True)).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    if plan.slug == "free" or plan.price <= 0:
        raise HTTPException(status_code=400, detail="Free plan needs no checkout — you are already on it")
    if not cashfree.is_configured():
        raise HTTPException(
            status_code=503,
            detail="Payments are not configured yet — the service owner has not added Cashfree keys.",
        )
    phone = normalize_phone(user.phone)
    if not phone:
        # Cashfree rejects the order without a phone number, so ask for it
        # up front instead of failing at the payment provider.
        raise HTTPException(
            status_code=400,
            detail="PHONE_REQUIRED: Add your mobile number to pay — the payment provider needs it for the order.",
        )
    order_id = cashfree.new_order_id()
    payment = Payment(
        user_id=user.id,
        cf_order_id=order_id,
        plan_slug=plan.slug,
        amount=plan.price,  # from DB, never the client
        currency=plan.currency,
        status="pending",
    )
    db.add(payment)
    db.commit()
    try:
        order = await cashfree.create_order(
            order_id=order_id,
            amount=plan.price,
            currency=plan.currency,
            customer_id=f"user-{user.id}",
            customer_email=user.email,
            customer_phone=phone,
        )
    except Exception as e:
        payment.status = "failed"
        db.commit()
        raise HTTPException(status_code=502, detail=f"Could not create payment order: {e}")
    return {
        "order_id": order.get("order_id", order_id),
        "payment_session_id": order.get("payment_session_id"),
        "cf_order_id": order_id,
        "mode": settings.cashfree_env,
    }


@router.get("/verify")
async def verify(order_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    payment = (
        db.query(Payment)
        .filter(Payment.cf_order_id == order_id, Payment.user_id == user.id)
        .first()
    )
    if not payment:
        raise HTTPException(status_code=404, detail="Order not found")
    if payment.status == "success":
        sub = (
            db.query(Subscription)
            .filter(Subscription.cf_order_id == order_id)
            .order_by(Subscription.id.desc())
            .first()
        )
        return {"status": "success", "subscription": subscription_dict(sub)}
    try:
        order = await cashfree.get_order(order_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not check payment status: {e}")
    if (order.get("order_status") or "").upper() == "PAID":
        cf_payment_id = None
        # Cashfree order response may include the payment id; best effort.
        sub = activate_order(db, payment, cf_payment_id)
        return {"status": "success", "subscription": subscription_dict(sub)}
    return {"status": (order.get("order_status") or "PENDING").lower(), "subscription": None}


@router.get("/mine")
def mine(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    sub = active_subscription(db, user.id)
    if not sub:
        sub = (
            db.query(Subscription)
            .filter(Subscription.user_id == user.id)
            .order_by(Subscription.id.desc())
            .first()
        )
    return {"subscription": subscription_dict(sub)}


@router.post("/cancel")
def cancel(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    sub = active_subscription(db, user.id)
    if not sub:
        raise HTTPException(status_code=404, detail="No active subscription")
    sub.status = "cancelled"
    db.commit()
    return {"subscription": subscription_dict(sub), "note": "Access continues until expires_at."}
