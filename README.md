# Qadam SaaS (Multi-tenant)

## Stack
- FastAPI API
- aiogram multi-bot worker (one bot per tenant)
- PostgreSQL + SQLAlchemy + Alembic

## Architecture
- Tenants are isolated by `tenant_id`.
- Public web/API access is tenant-scoped via `/t/{slug}/...`.
- Bot routing is tenant-scoped via tenant bot token (`tenants.bot_token`) and `bot_enabled`.
- Menu is stored only in DB (`menu_categories`, `menu_items`). No JSON menu fallback.

## Environment
Use `.env` (see `.env.example`):
- `DATABASE_URL`
- `API_BASE_URL`
- `PORT`
- `ADMIN_SECRET`
- `UPLOADS_DIR`
- `MENU_IMAGES_DIR`

`ADMIN_SECRET` protects internal operator/admin routes. Set it to a strong random value in production and never commit it.

## Production Notes

The canonical self-hosted deployment is `compose.production.yaml`: Caddy, FastAPI, the Telegram worker, and PostgreSQL 16. See `docs/production_runbook.md`.

For an optional Railway deployment, required resources are:
- web process: `uvicorn run_server:app --host 0.0.0.0 --port $PORT`
- worker process: `python run_bot.py`
- PostgreSQL database
- persistent upload storage: Railway Volume mounted at `/data`; S3-compatible storage is not implemented

Required production env vars:
- `DATABASE_URL`: Railway PostgreSQL connection string
- `ADMIN_SECRET`: strong random operator/admin secret
- `API_BASE_URL`: public HTTPS base URL, for example `https://qadam.example.com`
- `UPLOADS_DIR`: persistent hero/logo upload directory, for example `/data/uploads`
- `MENU_IMAGES_DIR`: persistent menu image directory, for example `/data/menu_images`
- `PORT`: provided by Railway for the web process

Health check:
- `GET /healthz` returns `{"status":"ok"}` without exposing secrets or tenant data.
- `GET /readyz` runs a short DB query and upload-storage write check; it returns `503` when DB or storage is unavailable and does not expose paths, credentials, or tracebacks.

SQLite demo mode:
- SQLite is supported for local/demo use with one web worker only. The startup migration flow in this repo is intended for that single-worker demo setup; do not run multiple Uvicorn workers on SQLite without a separate migration review.

## Run
Windows PowerShell, using the project virtual environment:

1. Activate venv:
   - `.\.venv\Scripts\Activate.ps1`
2. Install dependencies:
   - `python -m pip install -r requirements.txt`
3. Apply migrations:
   - `python -m alembic upgrade head`
4. Start API:
   - `python run_server.py`
5. Start bot worker in a second activated terminal:
   - `python run_bot.py`

If PowerShell script execution is restricted, run the venv interpreter directly:
- `.\.venv\Scripts\python.exe -m pip install -r requirements.txt`
- `.\.venv\Scripts\python.exe -m alembic upgrade head`
- `.\.venv\Scripts\python.exe run_server.py`

## Production Tenant Bootstrap
Single provisioning script:

`python -m scripts.bootstrap_tenant --slug demo --name "Demo" --admin-chat-id 123456 --bot-token <TOKEN> --bot-username demo_bot --enable-bot --plan standard --feature reservations --category "Main" --category "Drinks"`

What it does:
- creates or updates tenant
- writes bot config fields (`bot_token`, `bot_username`, `bot_enabled`)
- sets admin chat id
- creates initial empty categories (idempotent by title)
