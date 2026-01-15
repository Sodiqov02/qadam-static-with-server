import asyncio

from src.bot_init import get_bot, get_dispatcher
from src.handlers import admin as admin_handlers
from src.handlers import user as user_handlers


def setup_handlers() -> None:
    """Register all bot routers."""
    dp = get_dispatcher()
    dp.include_router(user_handlers.router)
    dp.include_router(admin_handlers.router)


async def main():
    setup_handlers()
    bot = get_bot()
    if not bot:
        raise RuntimeError("BOT_TOKEN is not configured")
    dp = get_dispatcher()
    # Make sure no webhook/polling session is active elsewhere
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
