"""Admin: overview, users, grant, providers (masked keys), plans CRUD.
Non-admin users get 403.
"""
from tests.conftest import auth, set_provider_key


def test_admin_overview(client, admin, user):
    r = client.get("/api/admin/overview", headers=auth(admin["token"]))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["users_total"] == 2
    assert body["free_users"] == 2
    assert body["paying_users"] == 0
    assert body["revenue_total"] == 0.0


def test_admin_forbidden_for_user(client, user):
    r = client.get("/api/admin/overview", headers=auth(user["token"]))
    assert r.status_code == 403


def test_admin_users_list(client, admin, user):
    r = client.get("/api/admin/users", headers=auth(admin["token"]))
    assert r.status_code == 200
    emails = [u["email"] for u in r.json()]
    assert "admin@test.local" in emails and "user@test.local" in emails


def test_admin_grant_activates_plan(client, admin, user):
    r = client.post(
        f"/api/admin/users/{user['user']['id']}/grant",
        json={"plan_slug": "monthly"},
        headers=auth(admin["token"]),
    )
    assert r.status_code == 200, r.text
    assert r.json()["subscription"]["plan_slug"] == "monthly"
    assert r.json()["subscription"]["status"] == "active"
    r = client.get("/api/auth/me", headers=auth(user["token"]))
    assert r.json()["user"]["plan_slug"] == "monthly"


def test_admin_providers_masked(client, admin, db):
    set_provider_key(db, "groq", "gsk_abcdefgh1234")
    r = client.get("/api/admin/providers", headers=auth(admin["token"]))
    assert r.status_code == 200
    masked = r.json()["keys_masked"]["groq"]
    assert masked is not None
    assert masked.endswith("1234")
    assert "gsk_abcdefgh" not in masked  # full key never returned
    assert r.json()["default_provider"] == "groq"


def test_admin_providers_put_and_clear(client, admin, db):
    r = client.put(
        "/api/admin/providers",
        json={"openai_key": "sk-test-openai-key-9999", "default_provider": "openai"},
        headers=auth(admin["token"]),
    )
    assert r.status_code == 200, r.text
    assert r.json()["default_provider"] == "openai"
    assert r.json()["keys_masked"]["openai"].endswith("9999")
    # Empty string = leave unchanged; null = clear.
    r = client.put(
        "/api/admin/providers",
        json={"openai_key": ""},
        headers=auth(admin["token"]),
    )
    assert r.json()["keys_masked"]["openai"].endswith("9999")
    r = client.put(
        "/api/admin/providers",
        json={"openai_key": None},
        headers=auth(admin["token"]),
    )
    assert r.json()["keys_masked"]["openai"] is None


def test_admin_plans_crud(client, admin):
    r = client.put(
        "/api/admin/plans/monthly",
        json={"price": 99.0},
        headers=auth(admin["token"]),
    )
    assert r.status_code == 200, r.text
    assert r.json()["price"] == 99.0
    # Public plans reflect the admin edit.
    r = client.get("/api/plans")
    monthly = [p for p in r.json() if p["slug"] == "monthly"][0]
    assert monthly["price"] == 99.0
    # Create a new plan.
    r = client.post(
        "/api/admin/plans",
        json={"slug": "quarterly", "name": "Quarterly", "price": 399.0, "duration_days": 90},
        headers=auth(admin["token"]),
    )
    assert r.status_code == 200, r.text
    assert r.json()["slug"] == "quarterly"


def test_admin_plans_forbidden_for_user(client, user):
    r = client.get("/api/admin/plans", headers=auth(user["token"]))
    assert r.status_code == 403
