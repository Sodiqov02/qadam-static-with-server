from typing import Optional

from aiogram import Bot
from src.bot_init import get_bot
from src.config import settings
from src.db_models import Tenant
from src.store import get_menu_for_tenant, get_order, list_reservations, tenant_has_plan


def _tget(obj, key, default=None):
    # Works for both dict-like and attribute objects (Tenant)
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)

def _get_bot() -> Optional[Bot]:
    if not settings.BOT_TOKEN:
        return None
    return get_bot()


async def _safe_send(chat_id: int, text: str) -> None:
    bot = _get_bot()
    if not bot:
        return
    try:
        await bot.send_message(chat_id=chat_id, text=text)
    except Exception:
        return


def _price_lookup(order: dict) -> dict:
    tenant = order.get("tenant")
    if not isinstance(tenant, Tenant):
        return {}
    menu = get_menu_for_tenant(tenant)
    mapping = {}
    for cat in menu.get("categories", []):
        for it in cat.get("items", []):
            mapping[str(it.get("id"))] = {
                "name": it.get("name", ""),
                "price": int(it.get("price") or 0),
            }
    return mapping


def _resolve_admin_chat_id(tenant: Tenant | None) -> int | None:
    chat_id = _tget(tenant, "admin_chat_id")
    if chat_id:
        return int(chat_id)
    if settings.ADMIN_CHAT_ID:
        return int(settings.ADMIN_CHAT_ID)
    return None


async def notify_admin(order_id: int):
    """Send a short order notification to the admin chat for the order's tenant."""
    order = get_order(order_id)
    if not order:
        return
    tenant = order.get("tenant")
    if not isinstance(tenant, Tenant):
        return

    # Skip duplicating bot-origin orders (bot already notifies admin)
    source = str(order.get("source") or "").lower()
    if source == "bot":
        return

    price_map = _price_lookup(order)
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
    chat_id = _resolve_admin_chat_id(tenant)
    if chat_id:
        await _safe_send(int(chat_id), text)


async def notify_reservation_created(tenant: Tenant, rid: int):
    chat_id = _resolve_admin_chat_id(tenant)
    if not chat_id:
        return

    items = list_reservations(tenant)
    r = next((x for x in items if x.get("id") == rid), None)

    if not r:
        text = f"[NEW RESERVATION #{rid}]\n(no details found)"
    else:
        text = (
            f"[NEW RESERVATION #{rid}]\n"
            f"Name: {r.get('name','')}\n"
            f"Phone: {r.get('phone','')}\n"
            f"Guests: {r.get('guests','')}\n"
            f"DateTime: {r.get('datetime','')}\n"
            f"Status: {r.get('status','')}\n"
            f"Table: {r.get('table_id','')}\n"
        )

    await _safe_send(int(chat_id), text)


async def notify_reservation_updated(tenant: Tenant, rid: int):
    chat_id = _resolve_admin_chat_id(tenant)
    if not chat_id:
        return

    items = list_reservations(tenant)
    r = next((x for x in items if x.get("id") == rid), None)

    if not r:
        text = f"[RESERVATION UPDATED #{rid}]\n(no details found)"
    else:
        text = (
            f"[RESERVATION UPDATED #{rid}]\n"
            f"Status: {r.get('status','')}\n"
            f"Name: {r.get('name','')}\n"
            f"Phone: {r.get('phone','')}\n"
            f"Guests: {r.get('guests','')}\n"
            f"DateTime: {r.get('datetime','')}\n"
        )

    await _safe_send(int(chat_id), text)


async def notify_order_status_changed(order_id: int, old_status: str | None, new_status: str) -> None:
    order = get_order(order_id)
    if not order:
        return
    tenant = order.get("tenant")
    if not isinstance(tenant, Tenant):
        return
    if not tenant_has_plan(tenant, "standard"):
        return
    customer = order.get("customer", {})
    chat_id = customer.get("chat_id")
    if not chat_id:
        return
    old_text = f" (was {old_status})" if old_status else ""
    text = f"Your order #{order_id} status is now {new_status}.{old_text}"
    await _safe_send(int(chat_id), text)
