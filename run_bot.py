import asyncio
import logging

from src.bot_manager import BotManager

logging.basicConfig(level=logging.INFO)


async def main():
    manager = BotManager()
    await manager.start()


if __name__ == "__main__":
    asyncio.run(main())
