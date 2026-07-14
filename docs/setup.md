# Qadam Local Server Setup

## Docker Compose (recommended)

Install Docker Desktop (Windows/macOS) or Docker Engine with the Compose plugin (Linux).

```bash
cp .env.example .env
docker compose up --build -d
docker compose ps
curl http://127.0.0.1:8000/healthz
curl http://127.0.0.1:8000/readyz
```

On PowerShell use `Copy-Item .env.example .env`. Set a strong local `ADMIN_SECRET` in `.env`; never commit that file. The API is published only at `127.0.0.1:8000`. The bot has no published port and reaches the API as `http://api:8000` through `QADAM_API_BASE_URL`.

For isolated testing, point Compose at a separate untracked env file with `QADAM_ENV_FILE`; the default remains `.env`.

```bash
docker compose logs -f api
docker compose logs -f bot
docker compose stop
docker compose down
```

`docker compose down` retains the named `qadam_data` volume. Do not use `down -v` unless intentionally deleting the SQLite database and uploads. Only one API worker and one bot replica are supported with SQLite; do not use `docker compose up --scale`.

Back up the complete data volume while services are stopped:

```bash
docker compose stop
docker run --rm -v qadam_qadam_data:/data -v "$PWD:/backup" alpine tar czf /backup/qadam-data.tgz -C /data .
docker compose start
```

Restore into an empty volume (this replaces its contents):

```bash
docker compose down
docker volume create qadam_qadam_data
docker run --rm -v qadam_qadam_data:/data -v "$PWD:/backup" alpine sh -c "rm -rf /data/* && tar xzf /backup/qadam-data.tgz -C /data"
docker run --rm --user 0 -v qadam_qadam_data:/data qadam:local chown -R 10001:10001 /data
docker compose up -d
```

The ownership step is required because the application image runs as UID/GID `10001`. For an online SQLite-only backup, use Python's `sqlite3.Connection.backup()` API instead of copying an active `.db` file; the stopped full-volume archive above also preserves uploads and SQLite sidecars consistently.

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
QADAM_API_BASE_URL
UPLOADS_DIR=/data/uploads
MENU_IMAGES_DIR=/data/menu_images
PORT
```

`API_BASE_URL` is the public browser-facing origin. `QADAM_API_BASE_URL` is used by the bot for internal HTTP calls and defaults to `API_BASE_URL` for non-Docker local runs.

Never commit `ADMIN_SECRET`, bot tokens, database URLs, or generated admin links.

Health check:

```txt
GET /healthz -> {"status":"ok"}
GET /readyz  -> {"status":"ready"} when the database and both upload directories are writable
```

`/healthz` is the liveness check. Use `/readyz` for deployment readiness; it returns `503` if the database or configured upload storage is unavailable.

Menu and branding uploads currently use the local filesystem only. Production must mount a persistent Railway Volume and set both `UPLOADS_DIR=/data/uploads` and `MENU_IMAGES_DIR=/data/menu_images`. S3 or other object storage is not implemented.

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
