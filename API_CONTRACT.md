# Interview Assistant SaaS — API Contract v1 (16 Nov 2026)

Parakeet-style subscription service. The user (Gautam Keshri) is the SERVICE
PROVIDER: he sets provider API keys + prices in the Admin panel; end users
only sign up, log in, subscribe via Cashfree, and use the app. NO API keys
ever live in frontend code or the desktop app — the backend holds them
(Fernet-encrypted in DB) and proxies all AI calls.

## Stack
- Backend: FastAPI + SQLAlchemy + PostgreSQL (Neon free), Render free tier.
  `~/workspace/interview-assistant-saas/backend/`
- Web frontend: Vite 6 + vanilla JS (existing `~/workspace/interview-assistant-web/`).
- Desktop: Electron (existing `~/workspace/interview-assistant-desktop/`).
- Payments: Cashfree PG (PROD keys via Render env vars only, never in code/chat).
- Auth: JWT (HS256, 7-day expiry), passlib bcrypt. First registered user = admin.

## Env vars (backend)
DATABASE_URL, JWT_SECRET, CASHFREE_APP_ID, CASHFREE_SECRET_KEY, CASHFREE_ENV
(PROD/SANDBOX), CORS_ORIGINS, ENCRYPTION_KEY (Fernet, generated at deploy).
No default secrets in code. No hard-coded API keys anywhere.

## Data model
- users: id, name, email (unique), password_hash, role (admin|user),
  plan_slug (free|weekly|monthly|yearly, default free), created_at.
- plans: id, slug (unique), name, price, currency (default INR), duration_days
  (free 0, weekly 7, monthly 30, yearly 365), sessions_limit (free 10, paid NULL
  = unlimited), minutes_per_session (free 10, paid NULL), mock_limit (free 1,
  paid NULL), features (JSON list), active (bool), sort_order.
  Defaults seeded on startup if table empty:
  free ₹0; weekly ₹6,499; monthly ₹12,999; yearly ₹49,999 ("₹4,167/mo billed yearly").
- subscriptions: id, user_id, plan_slug, status (active|expired|cancelled),
  starts_at, expires_at, cf_order_id, amount, currency, created_at.
- payments: id, user_id, cf_order_id (unique), plan_slug, amount, currency,
  status (pending|success|failed), cf_payment_id, created_at. Idempotent on
  cf_order_id — a webhook/return replay must never double-activate.
- provider_settings: single row (id=1): default_provider (groq|openai|gemini|
  claude), groq_key_enc, openai_key_enc, gemini_key_enc, claude_key_enc,
  groq_model (default openai/gpt-oss-120b), openai_model (default gpt-4o-mini),
  gemini_model (default gemini-2.0-flash), claude_model (default
  claude-sonnet-4-20250514), vision_model per provider (openai gpt-4o-mini,
  gemini gemini-2.0-flash, claude claude-sonnet-4-20250514, groq
  qwen/qwen3.8-27b). GET returns keys masked (last 4 chars only).
- usage: columns on users: sessions_used (int), mocks_used (int),
  reset logic: free-plan counters are lifetime caps (10 sessions, 1 mock).
- ai_usage_log: id, user_id, endpoint, provider, model, tokens_in/out (when
  known), ok, error, created_at. (For admin overview; keep writes cheap.)

## Auth endpoints
- POST /api/auth/signup {name, email, password} -> {token, user{id,name,email,role,plan_slug}}
  First user in DB becomes admin. Validate: email format, password >= 6 chars.
- POST /api/auth/login {email, password} -> same shape.
- GET /api/auth/me (Bearer) -> {user, subscription{plan_slug,status,expires_at}|null, usage{sessions_used,mocks_used,sessions_limit,mock_limit}}.
- All other /api/* (except /api/plans, /api/health, /api/auth/*, /api/webhooks/*)
  require Bearer token.

## Public
- GET /api/health -> {status:"ok"}.
- GET /api/plans -> active plans, public fields only, ordered by sort_order.

## Plans / subscription / Cashfree
- POST /api/subscriptions/checkout {plan_slug} (Bearer) -> creates a payment row
  (pending) + Cashfree order (x-api-version 2023-08-01, env PROD/SANDBOX from
  CASHFREE_ENV) and returns {order_id, payment_session_id, cf_order_id}.
  Amount/currency come from the DB plan — never trust client-sent prices.
  Free plan: no checkout; user is already on free.
- GET /api/subscriptions/verify?order_id=... (Bearer) -> calls Cashfree
  GET /pg/orders/{order_id}, if status PAID and payment row pending: mark
  success, create/extend subscription (starts now, expires now+duration_days),
  set user.plan_slug. Returns {status, subscription}.
- POST /api/webhooks/cashfree (no auth; verify HMAC-SHA256 signature with
  CASHFREE_SECRET_KEY over raw body + timestamp header, Cashfree format) ->
  on PAYMENT_SUCCESS: same idempotent activation as verify. Always 200 after
  handling (never leak internals).
- GET /api/subscriptions/mine (Bearer) -> current subscription or null.
- POST /api/subscriptions/cancel (Bearer) -> status cancelled (keeps access
  until expires_at).

## AI proxy (Bearer; plan gate on every call)
Gate helper: paid = user has subscription status active and expires_at > now.
Free: allow if sessions_used < plan.sessions_limit (for chat/vision/transcribe
inside a live session) — the frontend calls /api/sessions/start once per live
session; that endpoint enforces + increments sessions_used. Mock: /api/mocks/start
enforces mocks_used < mock_limit, increments. Paid: unlimited, still log usage.
If gate fails -> 402 {error:"PLAN_LIMIT", message:"...upgrade..."}.
- POST /api/sessions/start (Bearer) -> {ok, sessions_used, sessions_limit} or 402.
- POST /api/mocks/start (Bearer) -> {ok, mocks_used, mock_limit} or 402.
- POST /api/ai/chat {messages:[{role,content}], temperature?, max_tokens?}
  -> {text, provider, model}. Routes to default_provider with its key+model.
  Provider clients:
  - groq: POST https://api.groq.com/openai/v1/chat/completions (OpenAI shape).
  - openai: POST https://api.openai.com/v1/chat/completions (OpenAI shape).
  - gemini: POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key=KEY
    with {contents:[{parts:[{text}]}]}; reply text from candidates[0].content.parts.
  - claude: POST https://api.anthropic.com/v1/messages with
    x-api-key, anthropic-version: 2023-06-01, {model, max_tokens, messages}.
  If default provider has no key configured -> 503 {error:"NO_PROVIDER_KEY",
  message:"The service owner has not added an AI key yet."}. Pass provider
  errors through as {error} with the provider's message, never a stack trace.
- POST /api/ai/vision {image (data URL), prompt?} -> {text, provider, model}.
  Extract-the-question prompt is the DEFAULT prompt (same wording as the old
  clients: extract exact question/problem word-for-word, reply ONLY that text,
  or exactly "NO QUESTION FOUND"). Vision models per provider (see above).
  - groq/openai: OpenAI chat shape with image_url data URL.
  - gemini: generateContent with inlineData {mimeType, data (base64, no prefix)}.
  - claude: messages content [{type:"image", source:{type:"base64",
    media_type, data}}, {type:"text", text: prompt}]. Strip any <think>...</think>
    blocks from the returned text before responding.
- POST /api/ai/transcribe (multipart form, field "audio") -> {text}.
  Whisper via Groq (whisper-large-v3-turbo) if groq key set, else OpenAI
  (whisper-1) if openai key set, else 503 NO_PROVIDER_KEY. Same 5s-chunk
  contract as before: frontend sends complete standalone audio files.
- GET /api/ai/status (Bearer) -> {provider: default_provider, configured: bool,
  chat_model, vision_model} — so the UI can show "AI ready" or "owner must add a key".

## Admin (Bearer + role admin only, 403 otherwise)
- GET /api/admin/overview -> {users_total, paying_users, active_subscriptions,
  revenue_total (sum of success payments), ai_calls_today, free_users}.
- GET /api/admin/users -> [{id,name,email,role,plan_slug,created_at,
  subscription{plan_slug,status,expires_at}|null, sessions_used, mocks_used}].
- PATCH /api/admin/users/{id} {role?, plan_slug?} (plan change also adjusts
  subscription? No — only role + free/paid override note: keep it simple, role
  only + a separate grant below).
- POST /api/admin/users/{id}/grant {plan_slug, days?} -> creates an active
  subscription manually (owner-granted access, e.g. for testers).
- GET /api/admin/subscriptions -> all, newest first, with user email + plan.
- GET /api/admin/payments -> all payments, newest first.
- GET /api/admin/providers -> {default_provider, models, keys_masked:{groq,openai,gemini,claude}}.
- PUT /api/admin/providers {default_provider?, groq_key?, openai_key?,
  gemini_key?, claude_key?, *_model?} -> encrypt + store; empty string means
  "leave unchanged"; explicit null clears a key. Never return full keys.
- GET /api/admin/plans -> all plans incl. inactive.
- PUT /api/admin/plans/{slug} {name?, price?, currency?, duration_days?,
  sessions_limit?, minutes_per_session?, mock_limit?, features?, active?}.
- POST /api/admin/plans {slug, name, price, ...} -> create a new plan.

## Frontend contract (web + desktop)
- API base URL: web reads VITE_API_URL at build time (fallback
  https://interview-assistant-api.onrender.com — updated at deploy); desktop
  uses the same default, overridable in Settings.
- Auth screen first: Login / Signup tabs. Token in localStorage (web) /
  userData/settings.json (desktop). All API calls send Authorization: Bearer.
  401 -> back to login screen.
- Pricing section renders GET /api/plans. Subscribe button -> checkout ->
  Cashfree JS SDK (https://sdk.cashfree.com/js/ui/2.0.0/cashfree.sandbox.js or
  .prod.js — pick by CASHFREE_ENV the backend reports? Simpler: backend
  /api/subscriptions/checkout returns {payment_session_id, mode: "PROD"|"SANDBOX"}
  and the frontend loads the matching SDK script) -> on success redirect to
  /api/subscriptions/verify flow (frontend return page calls verify, shows result).
- Live session: on Start, call /api/sessions/start (402 -> show upgrade prompt).
  Mic: browser SpeechRecognition (web) / Whisper chunks (desktop) as before;
  transcription via /api/ai/transcribe; typed questions + screenshot via
  /api/ai/vision; answers via /api/ai/chat with resume+JD as system context.
  Mock interview: /api/mocks/start first, then /api/ai/chat per question/answer.
- No provider keys anywhere in frontend code or Settings UI for end users.
  Admin panel (new tab/view, admin role only): overview cards, users table,
  subscriptions + payments tables, plans editor, provider keys form (password
  inputs, masked display), grant-access action.
- Desktop: transparent window (transparent:true, backgroundColor '#00000000',
  CSS glass panel, toggle in Settings for solid vs transparent). Redesign both
  apps: modern glassmorphism, gradient accents, cleaner spacing/typography.
  Keep: resume upload/JD, documents, AI notes, saved sessions, question bank,
  discreet panel, hotkeys (desktop), screenshare honesty note.

## Verification (each builder, before handing back)
- Backend: `pip install -r requirements.txt`, `uvicorn main:app` boots,
  pytest passes (auth, plan gate, checkout price-from-DB, webhook idempotency,
  vision prompt shape), no secrets in code (grep for sk-, gsk_, xox, keys).
- Web: `npm run build` passes; login + pricing render against a local backend.
- Desktop: `node --check` on all changed JS; xvfb smoke start with no renderer
  errors; transparency flag present.
- Report: files changed, how to run, what is NOT done / needs the owner
  (Cashfree keys, provider keys, deploy).
