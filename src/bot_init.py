from typing import Optional

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

from src.config import settings

_bot: Optional[Bot] = None
_dp: Optional[Dispatcher] = None


def get_bot() -> Optional[Bot]:
    global _bot
    if _bot is None and settings.BOT_TOKEN:
        # Use plain text to avoid HTML parsing errors on messages with <id>, etc.
        _bot = Bot(token=settings.BOT_TOKEN, default=DefaultBotProperties(parse_mode=None))
    return _bot


def get_dispatcher() -> Dispatcher:
    global _dp
    if _dp is None:
        _dp = Dispatcher()
    return _dp


# Backward-compatible alias for dispatcher imports.
dp = get_dispatcher()
