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

Current Alembic head:

```txt
0012_menu_item_description_reconcile
```

Create or refresh the local DB:

```bash
set DATABASE_URL=sqlite:///./data/local_clean.db
python -m scripts.sync_db
python -m scripts.safe_seed --slug demo --name Demo --admin-chat-id 100000001 --plan standard
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
