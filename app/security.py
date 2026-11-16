"""Passwords (bcrypt via passlib), JWT (HS256), Fernet encryption for
provider keys. No secrets are ever hard-coded; ENCRYPTION_KEY / JWT_SECRET
come from env (see config.py).
"""
import re
from datetime import timedelta

import jwt
from cryptography.fernet import Fernet, InvalidToken
from passlib.context import CryptContext

from .config import settings
from .db import utcnow

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return pwd_context.verify(password, password_hash)
    except Exception:
        return False


def create_access_token(user_id: int) -> str:
    payload = {
        "sub": str(user_id),
        "exp": utcnow() + timedelta(days=settings.jwt_expire_days),
        "iat": utcnow(),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> int | None:
    try:
        payload = jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
        return int(payload["sub"])
    except Exception:
        return None


def _fernet() -> Fernet:
    key = settings.encryption_key.encode()
    # Accept a raw Fernet key, or derive one from an arbitrary secret string.
    try:
        return Fernet(key)
    except Exception:
        import base64
        import hashlib

        derived = base64.urlsafe_b64encode(hashlib.sha256(key).digest())
        return Fernet(derived)


def encrypt_value(plain: str | None) -> str | None:
    if plain is None:
        return None
    return _fernet().encrypt(plain.encode()).decode()


def decrypt_value(enc: str | None) -> str | None:
    if not enc:
        return None
    try:
        return _fernet().decrypt(enc.encode()).decode()
    except InvalidToken:
        return None


def mask_key(plain: str | None) -> str | None:
    """Masked display for admin: last 4 chars only, e.g. '••••abcd'."""
    if not plain:
        return None
    return "•" * max(0, len(plain) - 4) + plain[-4:]
