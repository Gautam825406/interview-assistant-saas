"""Interview Assistant SaaS backend — settings from env vars only.

No default secrets. JWT_SECRET / ENCRYPTION_KEY fall back to a random
ephemeral value (dev only, with a loud warning) so `uvicorn main:app` boots
locally without env vars; production MUST set them via Render env vars.
"""
import os
import secrets
import warnings


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _secret(name: str) -> str:
    val = _env(name)
    if val:
        return val
    warnings.warn(
        f"{name} not set — using a random ephemeral value (dev only). "
        f"Set {name} in the environment for production.",
        stacklevel=2,
    )
    return secrets.token_urlsafe(48)


class Settings:
    database_url: str = _env("DATABASE_URL", "sqlite:///./interview_assistant.db")
    jwt_secret: str = _secret("JWT_SECRET")
    jwt_algorithm: str = "HS256"
    jwt_expire_days: int = 7
    encryption_key: str = _secret("ENCRYPTION_KEY")
    cashfree_app_id: str = _env("CASHFREE_APP_ID")
    cashfree_secret_key: str = _env("CASHFREE_SECRET_KEY")
    cashfree_env: str = _env("CASHFREE_ENV", "SANDBOX").upper()
    cors_origins: list[str] = [
        o.strip() for o in _env("CORS_ORIGINS", "*").split(",") if o.strip()
    ]


settings = Settings()
