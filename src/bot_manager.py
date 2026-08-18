import asyncio
import json
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramAPIError, TelegramUnauthorizedError
from aiogram.utils.token import TokenValidationError
from sqlalchemy.exc import SQLAlchemyError

from src.handlers import admin as admin_handlers
from src.handlers import user as user_handlers
from src.notifier import close_bot_cache, release_tenant_bot
from src.store import disable_tenant_bot, list_enabled_bot_tenants

logger = logging.getLogger(__name__)


class BotManager:
    """Start one isolated aiogram bot per tenant.

    Each bot has its own Dispatcher and in-memory state, preventing cross-tenant leakage.
    """

    def __init__(self) -> None:
        self._tasks: dict[int, asyncio.Task] = {}
        self._fingerprints: dict[int, tuple] = {}
        self._retry_backoff_seconds = 2

    def _build_dispatcher(self, tenant) -> Dispatcher:
        dp = Dispatcher()
        dp.include_router(user_handlers.create_user_router(tenant))
        dp.include_router(admin_handlers.create_admin_router(tenant))
        return dp

    @staticmethod
    def _token_fingerprint(token: str) -> str:
        if ":" in token:
            return token.split(":", 1)[0][-4:]
        return token[-4:]

    @staticmethod
    def _runtime_fingerprint(tenant) -> tuple:
        return (
            str(tenant.bot_token or "").strip(),
            str(tenant.slug or ""),
            str(tenant.name or ""),
            int(tenant.admin_chat_id) if tenant.admin_chat_id else None,
            json.dumps(tenant.features or {}, sort_keys=True, separators=(",", ":")),
        )

    async def _run_bot(self, tenant) -> None:
        token = (tenant.bot_token or "").strip()
        bot = None
        try:
            bot = Bot(token=token, default=DefaultBotProperties(parse_mode=None))
            # stability fix: proactively validate token before polling loop.
            await bot.get_me()
        except (TokenValidationError, TelegramUnauthorizedError):
            logger.exception("bot_token_invalid tenant=%s", tenant.slug)
            disable_tenant_bot(tenant.id)
            await release_tenant_bot(tenant.id)
            if bot is not None:
                await bot.session.close()
            return
        except TelegramAPIError:
            logger.exception("bot_validation_failed tenant=%s", tenant.slug)
            if bot is not None:
                await bot.session.close()
            return

        dp = self._build_dispatcher(tenant)
        try:
            await bot.delete_webhook(drop_pending_updates=True)
            logger.info("bot_start tenant=%s", tenant.slug)
            await dp.start_polling(bot)
        except TelegramUnauthorizedError:
            logger.exception("bot_polling_unauthorized tenant=%s", tenant.slug)
            disable_tenant_bot(tenant.id)
            await release_tenant_bot(tenant.id)
        except TelegramAPIError:
            logger.exception("bot_polling_failed tenant=%s", tenant.slug)
        except asyncio.CancelledError:
            logger.info("bot_cancelled tenant=%s", tenant.slug)
            raise
        finally:
            if bot is not None:
                await bot.session.close()
            logger.info("bot_stopped tenant=%s", tenant.slug)

    def _cleanup_finished_tasks(self) -> None:
        for tenant_id, task in list(self._tasks.items()):
            if not task.done():
                continue
            try:
                task.result()
            except asyncio.CancelledError:
                pass
            except (TelegramAPIError, TokenValidationError, TelegramUnauthorizedError):
                logger.exception("bot_task_failed tenant_id=%s", tenant_id)
            except Exception as exc:
                logger.exception(
                    "bot_task_unexpected_failed tenant_id=%s exception_type=%s",
                    tenant_id,
                    type(exc).__name__,
                )
            self._tasks.pop(tenant_id, None)
            self._fingerprints.pop(tenant_id, None)

    async def _stop_task(self, tenant_id: int) -> None:
        task = self._tasks.pop(tenant_id, None)
        self._fingerprints.pop(tenant_id, None)
        if task is None:
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def _reconcile(self, tenants) -> None:
        seen_tenant_ids: set[int] = set()
        seen_tokens: set[str] = set()
        for tenant in tenants:
            token = (tenant.bot_token or "").strip()
            if not token:
                logger.warning("skip_tenant_missing_bot_token tenant=%s", tenant.slug)
                continue
            if token in seen_tokens:
                logger.error("skip_tenant_duplicate_bot_token tenant=%s", tenant.slug)
                continue
            seen_tokens.add(token)
            tenant_id = int(tenant.id)
            seen_tenant_ids.add(tenant_id)
            fingerprint = self._runtime_fingerprint(tenant)
            task = self._tasks.get(tenant_id)
            if task and not task.done() and self._fingerprints.get(tenant_id) == fingerprint:
                continue
            if task is not None:
                previous_fingerprint = self._fingerprints.get(tenant_id)
                await self._stop_task(tenant_id)
                if previous_fingerprint and previous_fingerprint[0] != token:
                    await release_tenant_bot(tenant_id)
            self._fingerprints[tenant_id] = fingerprint
            self._tasks[tenant_id] = asyncio.create_task(self._run_bot(tenant))

        for tenant_id in list(self._tasks):
            if tenant_id in seen_tenant_ids:
                continue
            await self._stop_task(tenant_id)
            await release_tenant_bot(tenant_id)
            logger.info("bot_task_cancelled tenant_id=%s", tenant_id)

    async def shutdown(self) -> None:
        for tenant_id in list(self._tasks):
            await self._stop_task(tenant_id)
        await close_bot_cache()

    async def start(self) -> None:
        # stability fix: worker stays alive and periodically reconciles active tenants.
        try:
            while True:
                try:
                    self._cleanup_finished_tasks()
                    tenants = list_enabled_bot_tenants()
                    await self._reconcile(tenants)

                    if not tenants and not self._tasks:
                        logger.warning("no_enabled_tenants_with_bot_token")

                    self._retry_backoff_seconds = 2
                    await asyncio.sleep(30)
                except SQLAlchemyError as exc:
                    delay = self._retry_backoff_seconds
                    logger.exception("bot_manager_db_failed exception_type=%s retry_seconds=%s", type(exc).__name__, delay)
                    await asyncio.sleep(delay)
                    self._retry_backoff_seconds = min(delay * 2, 30)
                except Exception as exc:
                    delay = self._retry_backoff_seconds
                    logger.exception(
                        "bot_manager_unexpected_failed exception_type=%s retry_seconds=%s",
                        type(exc).__name__,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    self._retry_backoff_seconds = min(delay * 2, 30)
        except asyncio.CancelledError:
            logger.info("bot_manager_cancelled")
            raise
        finally:
            await self.shutdown()
