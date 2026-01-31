import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

from src.handlers import admin as admin_handlers
from src.handlers import user as user_handlers
from src.store import list_enabled_bot_tenants

logger = logging.getLogger(__name__)


class BotManager:
    """Start one isolated aiogram bot per tenant.

    Each bot has its own Dispatcher and in-memory state, preventing cross-tenant leakage.
    """

    def __init__(self) -> None:
        self._tasks: list[asyncio.Task] = []

    def _build_dispatcher(self, tenant) -> Dispatcher:
        dp = Dispatcher()
        dp.include_router(user_handlers.create_user_router(tenant))
        dp.include_router(admin_handlers.create_admin_router(tenant))
        return dp

    async def _run_bot(self, tenant) -> None:
        bot = Bot(token=tenant.bot_token, default=DefaultBotProperties(parse_mode=None))
        dp = self._build_dispatcher(tenant)
        try:
            await bot.delete_webhook(drop_pending_updates=True)
            logger.info("bot_start tenant=%s", tenant.slug)
            await dp.start_polling(bot)
        except Exception:
            logger.exception("bot_polling_failed tenant=%s", tenant.slug)
        finally:
            await bot.session.close()
            logger.info("bot_stopped tenant=%s", tenant.slug)

    async def start(self) -> None:
        tenants = list_enabled_bot_tenants()
        if not tenants:
            raise RuntimeError("No enabled tenants with bot_token")
        for tenant in tenants:
            if not tenant.bot_token:
                continue
            self._tasks.append(asyncio.create_task(self._run_bot(tenant)))
        await asyncio.gather(*self._tasks, return_exceptions=True)
