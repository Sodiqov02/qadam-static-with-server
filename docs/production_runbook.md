# Qadam Production Runbook

## First Railway deploy checklist

- Create a Railway PostgreSQL database and set `DATABASE_URL`.
- Configure the web process from `Procfile`: `uvicorn run_server:app --host 0.0.0.0 --port $PORT`.
- Configure the worker process from `Procfile`: `python run_bot.py`.
- Set `API_BASE_URL` to the public HTTPS app URL.
- Set `ADMIN_SECRET` to a strong random value. Never commit or paste it into screenshots.
- Decide upload persistence before launch:
  - Railway Volume mounted at `/data`, with `UPLOADS_DIR=/data/uploads` and `MENU_IMAGES_DIR=/data/menu_images`; or
  - S3-compatible storage after implementing an adapter.
- Run one release, then verify migrations reached `alembic heads`.

## Verify after release

- Open `GET /healthz` and confirm `{"status":"ok"}`.
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
