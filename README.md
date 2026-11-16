# Interview Assistant SaaS — Backend

FastAPI + SQLAlchemy backend for the Parakeet-style subscription service.
The owner (Gautam) sets provider API keys + prices in the Admin panel; end
users only sign up, log in, subscribe via Cashfree, and use the app. No API
keys ever live in frontend code or the desktop app — this backend holds them
(Fernet-encrypted in DB) and proxies all AI calls.

Full API contract: `../API_CONTRACT.md`.

## Stack

- FastAPI, SQLAlchemy 2.x, Pydantic v2
- PostgreSQL (Neon free) in production; SQLite file locally
- JWT (HS256, 7-day expiry), passlib bcrypt
- Cashfree PG orders API `2023-08-01` + webhook (HMAC-SHA256)
- Providers: Groq, OpenAI, Gemini, Claude (chat / vision / Whisper)

## Run locally

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then edit: DATABASE_URL etc. (dev defaults work as-is)
uvicorn main:app --reload
```

- Health: `GET http://127.0.0.1:8000/api/health` → `{"status":"ok"}`
- Docs: `http://127.0.0.1:8000/docs`

The first user to sign up becomes **admin**. Plans are seeded on startup
(Free $0 / Weekly $78 / Monthly $149.90 / Yearly $599.90).

## Env vars

| Var | Purpose |
| --- | --- |
| `DATABASE_URL` | Postgres URL (Neon) or `sqlite:///./interview_assistant.db` locally |
| `JWT_SECRET` | HS256 signing secret (generate a long random string) |
| `ENCRYPTION_KEY` | Fernet key for provider keys (generate with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`) |
| `CASHFREE_APP_ID` / `CASHFREE_SECRET_KEY` | Cashfree PG keys (PROD) |
| `CASHFREE_ENV` | `PROD` or `SANDBOX` (default SANDBOX) |
| `CORS_ORIGINS` | Comma-separated allowed origins, or `*` for dev |

No default secrets are in code. `JWT_SECRET` / `ENCRYPTION_KEY` fall back to
a random ephemeral value with a warning if unset (dev only) — set them in
production or logins/keys will not survive a restart.

## Tests

```bash
pytest -q
```

Tests use an isolated in-memory SQLite DB and mock all Cashfree/provider
HTTP — no real network calls, no real keys.

## Deploy (Render, free tier)

1. Push this repo to GitHub.
2. Render → New → Blueprint → pick the repo (root directory: `backend`),
   or create a Web Service manually:
   - Build: `pip install -r requirements.txt`
   - Start: `uvicorn main:app --host 0.0.0.0 --port $PORT`
3. Set env vars in the Render dashboard (see table above). Create a free
   Neon Postgres database and paste its pooled connection string as
   `DATABASE_URL`.
4. Cashfree dashboard → Developers → Webhooks: set the notify URL to
   `https://<your-render-service>.onrender.com/api/webhooks/cashfree`.
5. Sign up in the app as the first user (becomes admin), then in the Admin
   panel add provider keys and confirm prices.

## Notes

- Amounts/currency for checkout always come from the DB plan, never the client.
- Webhook + verify activation is idempotent — replays never double-activate.
- Provider keys are stored Fernet-encrypted; admin reads show only the last 4 chars.
- Free plan: 10 lifetime live sessions (10 min each), 1 mock. Paid: unlimited.
