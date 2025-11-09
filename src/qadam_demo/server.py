import asyncio
import threading
from flask import Flask, request, jsonify, send_from_directory
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from .handlers import setup_routers
from .config import load_config
import os

app = Flask(__name__)
loop = None
bot = None
dp = None

def create_app():
    config = load_config()
    
    # Initialize event loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # Initialize bot and dispatcher
    bot = Bot(config["BOT_TOKEN"], default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(setup_routers())
    
    # Initialize static directory
    static_dir = os.path.join(os.path.dirname(__file__), 'static')
    
    # Store bot, dp, and loop in app config
    app.config['bot'] = bot
    app.config['dp'] = dp
    app.config['loop'] = loop
    
    @app.route('/')
    def root():
        return send_from_directory(static_dir, 'index.html')

    @app.route('/<path:path>')
    def send_files(path):
        return send_from_directory(static_dir, path)

    @app.post("/api/order")
    def api_order():
        data = request.get_json(force=True, silent=True) or {}
        name = data.get("name","—"); phone = data.get("phone","—")
        address = data.get("address","—"); items = data.get("items",[])
        total = data.get("total","—")

        text = (
            "<b>Yangi buyurtma</b>\n"
            f"👤 {name}\n☎️ {phone}\n📍 {address}\n"
            f"🧾 Jami: {total}\n"
            "— — —\n" +
            "\n".join(f"• {it.get('name')} ×{it.get('quantity',1)} = {it.get('price')}"
                    for it in items)
        )
        async def notify_admin():
            bot = app.config['bot']
            await bot.send_message(config["ADMIN_ID"], text)

        loop = app.config['loop']
        asyncio.run_coroutine_threadsafe(notify_admin(), loop)
        return jsonify({"ok": True})
    
    def run_bot():
        loop = app.config['loop']
        dp = app.config['dp']
        bot = app.config['bot']
        loop.run_until_complete(dp.start_polling(bot))

    threading.Thread(target=run_bot, daemon=True).start()
    return app

if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=5500, debug=True)