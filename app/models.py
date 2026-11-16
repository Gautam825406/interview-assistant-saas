"""SQLAlchemy models — see API_CONTRACT.md data model section."""
from sqlalchemy import JSON, Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text

from .db import Base, utcnow


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    email = Column(String(320), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, default="user")  # admin | user
    plan_slug = Column(String(50), nullable=False, default="free")
    sessions_used = Column(Integer, nullable=False, default=0)
    mocks_used = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=utcnow)


class Plan(Base):
    __tablename__ = "plans"

    id = Column(Integer, primary_key=True, index=True)
    slug = Column(String(50), unique=True, index=True, nullable=False)
    name = Column(String(100), nullable=False)
    price = Column(Float, nullable=False, default=0.0)
    currency = Column(String(10), nullable=False, default="USD")
    duration_days = Column(Integer, nullable=False, default=0)
    sessions_limit = Column(Integer, nullable=True)  # NULL = unlimited
    minutes_per_session = Column(Integer, nullable=True)
    mock_limit = Column(Integer, nullable=True)
    features = Column(JSON, nullable=False, default=list)
    active = Column(Boolean, nullable=False, default=True)
    sort_order = Column(Integer, nullable=False, default=0)


class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    plan_slug = Column(String(50), nullable=False)
    status = Column(String(20), nullable=False, default="active")  # active|expired|cancelled
    starts_at = Column(DateTime, nullable=False, default=utcnow)
    expires_at = Column(DateTime, nullable=True)
    cf_order_id = Column(String(100), nullable=True)
    amount = Column(Float, nullable=False, default=0.0)
    currency = Column(String(10), nullable=False, default="USD")
    created_at = Column(DateTime, nullable=False, default=utcnow)


class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    cf_order_id = Column(String(100), unique=True, nullable=False, index=True)
    plan_slug = Column(String(50), nullable=False)
    amount = Column(Float, nullable=False)
    currency = Column(String(10), nullable=False, default="USD")
    status = Column(String(20), nullable=False, default="pending")  # pending|success|failed
    cf_payment_id = Column(String(100), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)


class ProviderSettings(Base):
    __tablename__ = "provider_settings"

    id = Column(Integer, primary_key=True)  # single row, id=1
    default_provider = Column(String(20), nullable=False, default="groq")
    groq_key_enc = Column(Text, nullable=True)
    openai_key_enc = Column(Text, nullable=True)
    gemini_key_enc = Column(Text, nullable=True)
    claude_key_enc = Column(Text, nullable=True)
    groq_model = Column(String(100), nullable=False, default="openai/gpt-oss-120b")
    openai_model = Column(String(100), nullable=False, default="gpt-4o-mini")
    gemini_model = Column(String(100), nullable=False, default="gemini-2.0-flash")
    claude_model = Column(String(100), nullable=False, default="claude-sonnet-4-20250514")
    groq_vision_model = Column(String(100), nullable=False, default="qwen/qwen3.8-27b")
    openai_vision_model = Column(String(100), nullable=False, default="gpt-4o-mini")
    gemini_vision_model = Column(String(100), nullable=False, default="gemini-2.0-flash")
    claude_vision_model = Column(String(100), nullable=False, default="claude-sonnet-4-20250514")


class AIUsageLog(Base):
    __tablename__ = "ai_usage_log"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    endpoint = Column(String(50), nullable=False)
    provider = Column(String(20), nullable=False)
    model = Column(String(100), nullable=False, default="")
    tokens_in = Column(Integer, nullable=True)
    tokens_out = Column(Integer, nullable=True)
    ok = Column(Boolean, nullable=False, default=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
