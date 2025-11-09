from src.config import settings
from src.bot_init import bot
from src.store import get_order

async def notify_admin(order_id: int):
    order = get_order(order_id)
    if not order:
        return
    items = "\n".join([f"- {i['item_id']} x{i['qty']}" for i in order["items"]])
    cust = order["customer"]
    text = (
        f"🆕 <b>Новый заказ #{order_id}</b>\n"
        f"{items}\n\n"
        f"👤 {cust['name']}\n📞 {cust['phone']}\n🏠 {cust['address']}\n"
        f"💬 {cust.get('comment','—')}\n"
        f"Источник: {order['source']}"
    )
    await bot.send_message(chat_id=settings.ADMIN_CHAT_ID, text=text)
