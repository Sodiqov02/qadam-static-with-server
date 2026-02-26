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

## Run
1. Install dependencies:
   - `pip install -r requirements.txt`
2. Apply migrations:
   - `alembic upgrade head`
3. Start API:
   - `python run_server.py`
4. Start bot worker:
   - `python run_bot.py`

## Production Tenant Bootstrap
Single provisioning script:

`python -m scripts.bootstrap_tenant --slug demo --name "Demo" --admin-chat-id 123456 --bot-token <TOKEN> --bot-username demo_bot --enable-bot --plan standard --feature reservations --category "Main" --category "Drinks"`

What it does:
- creates or updates tenant
- writes bot config fields (`bot_token`, `bot_username`, `bot_enabled`)
- sets admin chat id
- creates initial empty categories (idempotent by title)

