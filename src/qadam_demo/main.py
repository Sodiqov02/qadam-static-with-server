import asyncio
from aiogram import Bot, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram import Dispatcher
from .handlers import setup_routers
from .config import load_config

async def set_commands(bot: Bot):
    """Set bot commands in menu"""
    commands = [
        types.BotCommand(command="start", description="🚀 Botni ishga tushirish"),
        types.BotCommand(command="menu", description="🍽 Taomlar menyusi"),
        types.BotCommand(command="cart", description="🛒 Savatchani ko'rish"),
        types.BotCommand(command="help", description="ℹ️ Yordam"),
    ]
    await bot.set_my_commands(commands)

async def start_bot():
    config = load_config()
    bot = Bot(config["BOT_TOKEN"], default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(setup_routers())
    
    # Устанавливаем команды бота
    await set_commands(bot)
    
    # Запускаем бота
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(start_bot())