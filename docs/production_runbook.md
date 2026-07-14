# Qadam Production Runbook

## Docker Compose VPS preview

The same application image can run behind Caddy without publishing FastAPI port 8000:

```bash
cp .env.example .env
# Set APP_ENV=production, API_BASE_URL=https://your-domain.example,
# ADMIN_SECRET, and QADAM_DOMAIN in .env.
docker compose -f compose.yaml -f compose.production.yaml config
docker compose -f compose.yaml -f compose.production.yaml up --build -d
```

Caddy listens on 80/443, obtains HTTPS certificates automatically, and stores certificate state in `caddy_data`. DNS must already point the configured domain to the VPS. This repository does not purchase, configure, or deploy a VPS. Keep `QADAM_API_BASE_URL=http://api:8000` for the bot. Run exactly one API worker and one bot replica while using SQLite.

Back up and restore `/data` using the volume procedure in `docs/setup.md`. A consistent SQLite backup requires stopping both services first.

## First Railway deploy checklist

- Create a Railway PostgreSQL database and set `DATABASE_URL`.
- Configure the web process from `Procfile`: `uvicorn run_server:app --host 0.0.0.0 --port $PORT`.
- Configure the worker process from `Procfile`: `python run_bot.py`.
- Set `API_BASE_URL` to the public HTTPS app URL.
- Set `ADMIN_SECRET` to a strong random value. Never commit or paste it into screenshots.
- Decide upload persistence before launch:
  - mount a persistent Railway Volume at `/data`;
  - set `UPLOADS_DIR=/data/uploads` and `MENU_IMAGES_DIR=/data/menu_images`.
- S3-compatible or other external object storage is not implemented. Do not configure uploads without the persistent Volume.
- Run one release, then verify migrations reached `alembic heads`.

## Verify after release

- Open `GET /healthz` and confirm `{"status":"ok"}`.
- Open `GET /readyz` and confirm `{"status":"ready"}`. A `503` means the database or configured upload directories are unavailable.
- Open `/admin/onboarding` and log in with the operator secret.
- Create a test tenant without a bot token.
- Open the generated public menu link `/t/{slug}`.
- Open the generated one-time admin menu link.
- Create a category, dish, and image upload.
- Place a test order from the public menu.
- Check web and worker logs for startup errors.

## Creating the first restaurant

- Ask the owner for restaurant name, desired slug, admin Telegram chat id, plan, and optional bot username/token.
- Open `/admin/onboarding`.
- Enter the operator secret.
- Use slug check before submitting.
- Create the tenant and send the generated admin link to the owner.
- If bot is enabled, verify `/admin` with the bot from the configured admin chat.

## Restart behavior

Persistent:
- PostgreSQL data: tenants, menu, orders, admin sessions, login tokens.
- Upload files only if `UPLOADS_DIR` and `MENU_IMAGES_DIR` are on persistent storage.

In-memory:
- Operator onboarding session cookie validation state.
- Telegram bot carts and in-progress checkout state.
- Bot polling tasks.

After Railway restart, operators may need to log in to onboarding again. Customers with in-progress Telegram carts may need to start over.

## Backups

- Enable Railway PostgreSQL backups or schedule regular database dumps.
- Back up the upload volume or object storage bucket on the same cadence as the database.
- Before risky migrations, take a database backup and record the running commit/tag.

## Missing uploads recovery

- Confirm `UPLOADS_DIR` and `MENU_IMAGES_DIR` point at the expected persistent mount.
- Check whether files exist under the tenant slug directory.
- Restore files from the upload backup.
- If files cannot be restored, re-upload affected menu images in admin and save the dish again.

## Invalid Telegram bot token

- Worker logs `bot_token_invalid` or `bot_polling_unauthorized`.
- The worker disables the tenant bot to avoid repeated failures.
- Get a valid token from BotFather.
- Update the tenant through onboarding or an internal admin repair process.
- Re-enable the bot and wait for the worker reconciliation loop, or restart the worker.

## Rotate `ADMIN_SECRET`

- Set the new `ADMIN_SECRET` in Railway variables.
- Redeploy or restart the web process.
- Existing operator onboarding sessions stop working because session validation is in memory.
- Generate and share new operator instructions. Do not share the old secret.

## Rollback checklist

- Record current commit/tag, database revision, and active env vars.
- Confirm whether the target rollback commit supports the current database revision.
- Prefer rolling forward for schema changes unless a tested downgrade exists.
- Restore database backup only if data compatibility is broken and downtime is accepted.
- Restore uploads from backup if the rollback changes upload paths or storage mounts.
- Verify `/healthz`, public menu, admin menu, onboarding, and worker logs after rollback.
