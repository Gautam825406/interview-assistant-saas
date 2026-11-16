"""Plan gate: free caps (10 sessions, 1 mock) -> 402 PLAN_LIMIT;
paid users pass without limit."""
from tests.conftest import auth


def _start_sessions(client, token, n):
    last = None
    for _ in range(n):
        last = client.post("/api/sessions/start", headers=auth(token))
    return last


def test_free_session_limit_402(client, user):
    r = _start_sessions(client, user["token"], 10)
    assert r.status_code == 200
    assert r.json()["sessions_used"] == 10
    r = client.post("/api/sessions/start", headers=auth(user["token"]))
    assert r.status_code == 402
    assert r.json()["detail"]["error"] == "PLAN_LIMIT"


def test_free_mock_limit_402(client, user):
    r = client.post("/api/mocks/start", headers=auth(user["token"]))
    assert r.status_code == 200
    assert r.json()["mocks_used"] == 1
    r = client.post("/api/mocks/start", headers=auth(user["token"]))
    assert r.status_code == 402
    assert r.json()["detail"]["error"] == "PLAN_LIMIT"


def test_paid_user_unlimited(client, admin, user):
    # Admin grants the weekly plan to the user.
    r = client.post(
        f"/api/admin/users/{user['user']['id']}/grant",
        json={"plan_slug": "weekly"},
        headers=auth(admin["token"]),
    )
    assert r.status_code == 200, r.text
    r = _start_sessions(client, user["token"], 15)
    assert r.status_code == 200
    assert r.json()["sessions_used"] == 0  # paid users don't consume the free cap
    r = client.post("/api/mocks/start", headers=auth(user["token"]))
    assert r.status_code == 200


def test_ai_chat_gate_free_exhausted_402(client, user):
    _start_sessions(client, user["token"], 10)
    r = client.post(
        "/api/ai/chat",
        json={"messages": [{"role": "user", "content": "hi"}]},
        headers=auth(user["token"]),
    )
    assert r.status_code == 402
    assert r.json()["detail"]["error"] == "PLAN_LIMIT"
