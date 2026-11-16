"""Phone numbers: normalisation, PATCH /me, and the users.phone migration."""
from sqlalchemy import inspect, text

from app.db import ensure_user_phone_column
from app.phone import normalize_phone
from tests.conftest import auth


def test_normalize_phone():
    assert normalize_phone("+91 98765 43210") == "9876543210"
    assert normalize_phone("91-9876543210") == "9876543210"
    assert normalize_phone("09876543210") == "9876543210"
    assert normalize_phone("98765 43210") == "9876543210"
    assert normalize_phone("9876543210") == "9876543210"
    assert normalize_phone("12345") is None
    assert normalize_phone("98765432101") is None
    assert normalize_phone("") is None
    assert normalize_phone(None) is None


def test_patch_me_saves_phone(client, user_no_phone):
    r = client.patch(
        "/api/auth/me",
        json={"phone": "+91 98765 43210"},
        headers=auth(user_no_phone["token"]),
    )
    assert r.status_code == 200, r.text
    assert r.json()["user"]["phone"] == "9876543210"
    me = client.get("/api/auth/me", headers=auth(user_no_phone["token"]))
    assert me.json()["user"]["phone"] == "9876543210"


def test_patch_me_rejects_bad_phone(client, user_no_phone):
    r = client.patch(
        "/api/auth/me",
        json={"phone": "12345"},
        headers=auth(user_no_phone["token"]),
    )
    assert r.status_code == 400


def test_signup_requires_phone(client):
    r = client.post(
        "/api/auth/signup",
        json={"name": "No Phone", "email": "x@test.local", "password": "password123"},
    )
    assert r.status_code == 400
    assert "Mobile number" in r.text


def test_signup_rejects_bad_phone(client):
    r = client.post(
        "/api/auth/signup",
        json={
            "name": "Bad Phone",
            "email": "x@test.local",
            "password": "password123",
            "phone": "12345",
        },
    )
    assert r.status_code == 400


def test_signup_stores_normalised_phone(client):
    r = client.post(
        "/api/auth/signup",
        json={
            "name": "With Phone",
            "email": "withphone@test.local",
            "password": "password123",
            "phone": "+91 98765 43210",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["user"]["phone"] == "9876543210"


def test_ensure_phone_column_adds_missing_column():
    # Simulate a database built by an older release: users table with
    # no phone column. The migration must add it, and be idempotent.
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool

    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    with eng.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE users (id INTEGER PRIMARY KEY, name VARCHAR(200), "
                "email VARCHAR(320), password_hash VARCHAR(255), role VARCHAR(20), "
                "plan_slug VARCHAR(50), sessions_used INTEGER, mocks_used INTEGER, "
                "created_at DATETIME)"
            )
        )
    assert "phone" not in [
        c["name"] for c in inspect(eng).get_columns("users")
    ]
    ensure_user_phone_column(eng)
    assert "phone" in [c["name"] for c in inspect(eng).get_columns("users")]
    ensure_user_phone_column(eng)  # second run is a no-op
    assert "phone" in [c["name"] for c in inspect(eng).get_columns("users")]
