# Qadam Local Server Setup

## Run server

```bash
python run_server.py
```

Server:

```txt
http://127.0.0.1:8000
```

## Demo tenant

```txt
/t/demo
/t/demo/admin
/admin/menu/demo
```

## Local database

Fresh local DB:

```txt
data/local_clean.db
```

Check the current Alembic head instead of hardcoding it in local notes:

```bash
alembic heads
```

At v0.5 the expected head includes `0013_tenant_branding_fields`.

Create or refresh the local DB:

```bash
set DATABASE_URL=sqlite:///./data/local_clean.db
set ADMIN_SECRET=dev_only_admin_secret
python -m scripts.sync_db
python -m scripts.safe_seed --slug demo --name Demo --admin-chat-id 100000001 --plan standard
```

Local development can use the clearly marked fallback `dev_only_admin_secret` when `ADMIN_SECRET` is not set. Production-like environments must set a strong `ADMIN_SECRET`; `change_me`, empty values, and the dev fallback are rejected.

## Production environment

Railway needs:

```txt
web process:    uvicorn run_server:app --host 0.0.0.0 --port $PORT
worker process: python run_bot.py
PostgreSQL
persistent upload storage: Railway Volume at /data or external object storage
```

Required env vars:

```txt
DATABASE_URL
ADMIN_SECRET
API_BASE_URL
UPLOADS_DIR=/data/uploads
MENU_IMAGES_DIR=/data/menu_images
PORT
```

Never commit `ADMIN_SECRET`, bot tokens, database URLs, or generated admin links.

Health check:

```txt
GET /healthz -> {"status":"ok"}
```

## Telegram worker

```bash
python run_bot.py
```

The current demo tenant has no bot token, so the worker may show:

```txt
no_enabled_tenants_with_bot_token
```

## Smoke checks

Verified locally:

```txt
/                            200
/t/demo                      200
/t/demo/admin                200
/admin/menu/demo             200
/t/demo/menu                 200
image upload                 ok
order flow                   ok
admin API                    ok
telegram worker boot         ok
```
