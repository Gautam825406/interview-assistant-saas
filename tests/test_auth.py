"""Auth: signup/login, first-user-is-admin, validation, /me."""
from tests.conftest import auth, signup


def test_signup_first_user_is_admin(client):
    res = signup(client, "first@test.local", name="First")
    assert res["user"]["role"] == "admin"
    assert res["user"]["plan_slug"] == "free"
    assert res["token"]


def test_signup_second_user_is_user(client, admin):
    res = signup(client, "second@test.local", name="Second")
    assert res["user"]["role"] == "user"


def test_signup_duplicate_email_400(client, admin):
    r = client.post(
        "/api/auth/signup",
        json={"name": "Dup", "email": "admin@test.local", "password": "secret123"},
    )
    assert r.status_code == 400


def test_signup_short_password_400(client):
    r = client.post(
        "/api/auth/signup",
        json={"name": "Short", "email": "short@test.local", "password": "123"},
    )
    assert r.status_code == 400


def test_signup_bad_email_400(client):
    r = client.post(
        "/api/auth/signup",
        json={"name": "Bad", "email": "not-an-email", "password": "secret123"},
    )
    assert r.status_code == 400


def test_login_ok_and_wrong_password(client, admin):
    r = client.post(
        "/api/auth/login",
        json={"email": "admin@test.local", "password": "secret123"},
    )
    assert r.status_code == 200
    assert r.json()["user"]["email"] == "admin@test.local"
    r = client.post(
        "/api/auth/login",
        json={"email": "admin@test.local", "password": "wrongpass"},
    )
    assert r.status_code == 401


def test_me_requires_auth(client):
    assert client.get("/api/auth/me").status_code == 401


def test_me_returns_usage_and_limits(client, user):
    r = client.get("/api/auth/me", headers=auth(user["token"]))
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["plan_slug"] == "free"
    assert body["subscription"] is None
    assert body["usage"]["sessions_used"] == 0
    assert body["usage"]["sessions_limit"] == 10
    assert body["usage"]["mock_limit"] == 1


def test_public_plans_seeded(client):
    r = client.get("/api/plans")
    assert r.status_code == 200
    slugs = [p["slug"] for p in r.json()]
    assert slugs == ["free", "weekly", "monthly", "yearly"]
    monthly = [p for p in r.json() if p["slug"] == "monthly"][0]
    assert monthly["price"] == 12999.0
    assert monthly["currency"] == "INR"
    assert monthly["sessions_limit"] is None  # unlimited
