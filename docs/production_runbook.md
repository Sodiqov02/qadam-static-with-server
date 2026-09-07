# Qadam Production Runbook

## Docker Compose VPS preview

The same application image can run behind Caddy without publishing FastAPI port 8000:

```bash
cp .env.example .env
# Set API_BASE_URL=https://your-domain.example, PUBLIC_BASE_URL=https://your-domain.example,
# ADMIN_SECRET, QADAM_DOMAIN,
# and a URL-safe POSTGRES_PASSWORD in .env.
docker compose -f compose.production.yaml config
docker compose -f compose.production.yaml up --build -d
```

Caddy listens on 80/443, obtains HTTPS certificates automatically, and stores certificate state in `caddy_data`. DNS must already point the configured domain to the VPS. This repository does not purchase, configure, or deploy a VPS. Production Compose runs PostgreSQL 16 on the private `app_internal` network and persists it in `qadam_postgres_data`. Keep `QADAM_API_BASE_URL=http://api:8000` for the bot. Caddy and API share the narrow `172.30.0.0/29` `caddy_api` network, with deterministic addresses `172.30.0.2` for Caddy and `172.30.0.3` for API; Uvicorn trusts proxy headers only from Caddy and loopback. The bot is attached only to `app_internal`. API rate limiting is process-local, so run one API replica until a shared rate-limit backend is implemented.

Order and reservation notifications are best-effort. The database write completes before a Telegram notification is scheduled, and the HTTP response does not wait for Telegram. Uvicorn normally lets in-flight background tasks finish during graceful shutdown, but a crash, forced kill, graceful-shutdown timeout, or abrupt restart can lose a notification. The saved order or reservation remains in the database, delivery is not guaranteed, and there is no automatic retry queue.

Back up both `qadam_postgres_data` and `/data` uploads. Prefer `pg_dump`/`pg_restore` for database backups rather than copying a live PostgreSQL volume.

## Optional Railway deploy checklist

- Create a Railway PostgreSQL database and set `DATABASE_URL`.
- Configure the web process from `Procfile`: `uvicorn run_server:app --host 0.0.0.0 --port $PORT`.
- Configure the worker process from `Procfile`: `python run_bot.py`.
- Set `API_BASE_URL` to the public HTTPS app URL.
- Set `PUBLIC_BASE_URL` to the same public HTTPS origin. Telegram admin links use this value.
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

For a repeatable two-tenant pilot check, run the repository smoke script from a trusted operator machine:

```bash
python scripts/pilot_live_smoke.py run \
  --base-url https://your-domain.example \
  --operator-secret "$ADMIN_SECRET" \
  --state /tmp/qadam-pilot-state.json

# After restarting the stack:
python scripts/pilot_live_smoke.py verify-restart \
  --base-url https://your-domain.example \
  --state /tmp/qadam-pilot-state.json
```

The temporary state file contains short-lived validation cookies. Keep it outside the repository, restrict access to it, and delete it after the restart check. The smoke creates two uniquely named test tenants and persistent test orders; use a disposable validation database or remove those records through an approved operator procedure.

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
