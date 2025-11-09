from dotenv import load_dotenv
from aiogram import Bot
import asyncio, os

load_dotenv()

async def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        print("BOT_TOKEN not set in .env")
        return
    b = Bot(token=token)
    ok = await b.delete_webhook(drop_pending_updates=True)
    print("DeleteWebhook:", ok)
    await b.session.close()

if __name__ == '__main__':
    asyncio.run(main())
