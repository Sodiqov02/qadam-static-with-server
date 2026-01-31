# Qadam demo (multi-tenant)

## Quick start
- Установить зависимости: `pip install -r requirements.txt` (или `pip install -e .`).
- Подготовить `.env` (см. `.env.example`): `BOT_TOKEN`, `ADMIN_CHAT_ID`, `API_BASE_URL`, `DATABASE_URL` (PostgreSQL рекомендован, можно SQLite для локального прогона), `PORT`.
- Применить миграции: `alembic upgrade head` (использует `DATABASE_URL`).
- Запустить API: `python run_server.py` (поднимет FastAPI на `PORT`).
- Запустить бота: `python run_bot.py` (aiogram, тот же `.env`). Убедитесь, что `API_BASE_URL` указывает на API (например, http://localhost:8000).

## Быстрые вспомогательные команды
- Создать нового клиента: `python scripts/create_tenant.py --slug demo --name "Demo" --admin_chat_id 123` (добавьте `--features reservations` чтобы включить бронь).
- Смоук-тест (когда API запущен): `python scripts/smoke_test.py --base-url http://localhost:8000 --slug smoke` (импортирует меню, создаёт заказ, обновляет статусы).

## API заметки
- Старые эндпоинты `/menu` и `/orders` работают как раньше и привязаны к tenant `default` (если в БД нет меню — используется fallback из `data/menu.json`).
- Новые мульти-tenant маршруты: `/t/{slug}/menu`, `/t/{slug}/orders`, `/t/{slug}/reservations` (+ PATCH для статуса).
- Reservation-флоу доступен только если в `tenant.features` есть `reservations: true`.

## Бот
- Команда `/start <slug>` или `/tenant <slug>` выбирает заведение, дальше все операции идут через `/t/{slug}/...`.
- Меню/корзина/checkout не меняются по UX, просто работают с выбранным tenant.

## Multi-bot architecture (one bot per tenant)
- Каждый tenant имеет собственный Telegram бот: поля `tenants.bot_token`, `tenants.bot_username`, `tenants.bot_enabled`.
- `run_bot.py` запускает `BotManager`, который поднимает отдельный aiogram бот и Dispatcher для каждого tenant с включённым ботом.
- Обработчики бота создаются через фабрики `create_user_router` / `create_admin_router` и получают tenant в контексте, без передачи slug от пользователя.
- Изоляция: каждый бот оперирует только своим tenant_id, общих глобальных стейтов между ботами нет.
