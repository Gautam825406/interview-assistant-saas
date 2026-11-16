"""Auth: signup (first user becomes admin), login, me."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..gate import active_subscription, get_plan
from ..models import Subscription, User
from ..phone import normalize_phone
from ..security import EMAIL_RE, create_access_token, hash_password, verify_password
from ..settings_util import subscription_dict, user_dict

router = APIRouter(prefix="/api/auth", tags=["auth"])


class SignupIn(BaseModel):
    name: str
    email: str
    password: str


class LoginIn(BaseModel):
    email: str
    password: str


class MeUpdateIn(BaseModel):
    name: str | None = None
    phone: str | None = None


def _auth_response(user: User) -> dict:
    return {"token": create_access_token(user.id), "user": user_dict(user)}


@router.post("/signup")
def signup(body: SignupIn, db: Session = Depends(get_db)):
    name = (body.name or "").strip()
    email = (body.email or "").strip().lower()
    password = body.password or ""
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")
    if not EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="Invalid email address")
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=400, detail="An account with this email already exists")
    role = "admin" if db.query(User).count() == 0 else "user"
    user = User(name=name, email=email, password_hash=hash_password(password), role=role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return _auth_response(user)


@router.post("/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    email = (body.email or "").strip().lower()
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(body.password or "", user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return _auth_response(user)


@router.patch("/me")
def update_me(body: MeUpdateIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if body.name is not None:
        name = (body.name or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="Name is required")
        user.name = name
    if body.phone is not None:
        phone = normalize_phone(body.phone)
        if phone is None:
            raise HTTPException(status_code=400, detail="Enter a valid 10-digit mobile number")
        user.phone = phone
    db.commit()
    db.refresh(user)
    return {"user": user_dict(user)}


@router.get("/me")
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    sub = active_subscription(db, user.id)
    if not sub:
        sub = (
            db.query(Subscription)
            .filter(Subscription.user_id == user.id)
            .order_by(Subscription.id.desc())
            .first()
        )
    plan = get_plan(db, user.plan_slug) or get_plan(db, "free")
    return {
        "user": user_dict(user),
        "subscription": subscription_dict(sub),
        "usage": {
            "sessions_used": user.sessions_used,
            "mocks_used": user.mocks_used,
            "sessions_limit": plan.sessions_limit if plan else None,
            "mock_limit": plan.mock_limit if plan else None,
        },
    }
