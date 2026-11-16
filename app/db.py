"""Database engine/session. SQLite for local dev/tests, PostgreSQL (Neon)
in production via DATABASE_URL. All datetimes are naive UTC — portable
across both backends. No Postgres-only syntax anywhere.
"""
from datetime import datetime, timezone

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker

from .config import settings

connect_args = {}
if settings.database_url.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
    # Neon (serverless Postgres) closes idle pooled connections; without
    # this, the next request gets a dead connection and dies with
    # "SSL connection has been closed unexpectedly" (saw this live on
    # POST /api/subscriptions/checkout, 16 Nov 2026). pre_ping tests the
    # connection before use and discards dead ones; recycle caps lifetime.
    pool_pre_ping=True,
    pool_recycle=300,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def ensure_user_phone_column(engine):
    """Add users.phone on databases created before the column existed.

    create_all() never adds a column to an existing table, so a database
    built by an older release needs this one-time ALTER. Idempotent:
    does nothing when the column is already there. Works on Postgres
    and SQLite (both support ADD COLUMN; the inspector check keeps it
    safe to run on every startup).
    """
    insp = inspect(engine)
    if "users" not in insp.get_table_names():
        return
    cols = [c["name"] for c in insp.get_columns("users")]
    if "phone" in cols:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE users ADD COLUMN phone VARCHAR(20)"))


def utcnow() -> datetime:
    """Naive UTC now — consistent on SQLite and Postgres."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
