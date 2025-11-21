import json
from pathlib import Path

from src.bot_init import bot
from src.config import settings
from src.store import get_order

MENU_PATH = Path(__file__).resolve().parents[1] / "data" / "menu.json"


def _price_lookup() -> dict:
    try:
        data = json.loads(MENU_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    mapping = {}
    for cat in data.get("categories", []):
        for it in cat.get("items", []):
            mapping[str(it.get("id"))] = {
                "name": it.get("name", ""),
                "price": int(it.get("price") or 0),
            }
    return mapping


async def notify_admin(order_id: int):
    """Send a short order notification to the admin chat."""
    order = get_order(order_id)
    if not order:
        return
    # Bot уже шлет отдельное уведомление; чтобы не дублировать, пропускаем bot-источник
    source = str(order.get("source") or "").lower()
    if source == "bot":
        return

    price_map = _price_lookup()
    total = 0
    item_lines = []
    for i in order["items"]:
        meta = price_map.get(str(i["item_id"]), {})
        name = meta.get("name") or i["item_id"]
        price = meta.get("price", 0)
        line_total = price * int(i.get("qty", 0) or 0)
        total += line_total
        item_lines.append(f"- {name} x{i['qty']} = {line_total} so'm")

    cust = order["customer"]
    comment = cust.get("comment") or "-"

    text = "\n".join(
        [
            f"[NEW ORDER #{order_id}]",
            *item_lines,
            f"Jami: {total} so'm",
            "",
            f"Name: {cust['name']}",
            f"Phone: {cust['phone']}",
            f"Address: {cust['address']}",
            f"Comment: {comment}",
            f"Source: {order['source']}",
        ]
    )
    await bot.send_message(chat_id=settings.ADMIN_CHAT_ID, text=text)
