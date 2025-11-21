from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from src.config import settings

# Use plain text to avoid HTML parsing errors on messages with <id>, etc.
bot = Bot(token=settings.BOT_TOKEN, default=DefaultBotProperties(parse_mode=None))
dp = Dispatcher()
