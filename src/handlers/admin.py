from functools import wraps
from aiogram import Router, types
from aiogram.filters import Command
from aiogram.exceptions import TelegramAPIError

from src.config import settings
from src.db_models import Tenant
from src.notifier import notify_order_status_changed
from src.store import create_admin_login_token_for_tenant, update_order_status


def create_admin_router(tenant: Tenant) -> Router:
    router = Router()
    user_last_message_id: dict[int, int] = {}

    def _admin_menu_url(token: str) -> str:
        base_url = (settings.API_BASE_URL or "").rstrip("/")
        if base_url.endswith("/api"):
            base_url = base_url[:-4]
        if not base_url:
            base_url = "http://localhost:8000"
        return f"{base_url}/admin/menu/{tenant.slug}?admin_token={token}"

    def admin_only(func):
        @wraps(func)
        async def wrapper(message: types.Message, *args, **kwargs):
            if not message.chat:
                return
            if not tenant.admin_chat_id:
                return
            if int(message.chat.id) != int(tenant.admin_chat_id):
                return
            return await func(message, *args, **kwargs)

        return wrapper

    async def _delete_last_reply(bot, chat_id: int) -> None:
        last_message_id = user_last_message_id.get(chat_id)
        if not bot or not last_message_id:
            return
        try:
            await bot.delete_message(chat_id=chat_id, message_id=last_message_id)
        except TelegramAPIError:
            return

    async def _safe_delete_command_message(message: types.Message) -> None:
        try:
            await message.delete()
        except TelegramAPIError:
            return

    async def _answer_admin(message: types.Message, text: str) -> None:
        if not message.chat:
            return
        chat_id = int(message.chat.id)
        await _delete_last_reply(message.bot, chat_id)
        sent = await message.answer(text)
        user_last_message_id[chat_id] = sent.message_id
        await _safe_delete_command_message(message)

    @router.message(Command("approve"))
    @admin_only
    async def approve(message: types.Message):
        if not message.text:
            return await _answer_admin(message, "Format: /approve 12")
        parts = message.text.split()
        if len(parts) != 2 or not parts[1].isdigit():
            return await _answer_admin(message, "Format: /approve 12")
        oid = int(parts[1])
        ok, order, _, prev, new = update_order_status(
            oid,
            "ACCEPTED",
            tenant_id=tenant.id,
            admin_chat_id=message.chat.id if message.chat else None,
            enforce_workflow=True,
        )
        if ok and order and new:
            await notify_order_status_changed(order.id, tenant.id, prev, new)
        await _answer_admin(message, "Tasdiqlandi." if ok else "Buyurtma topilmadi yoki status noto'g'ri.")

    @router.message(Command("reject"))
    @admin_only
    async def reject(message: types.Message):
        if not message.text:
            return await _answer_admin(message, "Format: /reject 12")
        parts = message.text.split()
        if len(parts) != 2 or not parts[1].isdigit():
            return await _answer_admin(message, "Format: /reject 12")
        oid = int(parts[1])
        ok, order, _, prev, new = update_order_status(
            oid,
            "CANCELED",
            tenant_id=tenant.id,
            admin_chat_id=message.chat.id if message.chat else None,
            enforce_workflow=True,
        )
        if ok and order and new:
            await notify_order_status_changed(order.id, tenant.id, prev, new)
        await _answer_admin(message, "Rad etildi." if ok else "Buyurtma topilmadi yoki status noto'g'ri.")

    @router.message(Command("done"))
    @admin_only
    async def done(message: types.Message):
        if not message.text:
            return await _answer_admin(message, "Format: /done 12")
        parts = message.text.split()
        if len(parts) != 2 or not parts[1].isdigit():
            return await _answer_admin(message, "Format: /done 12")
        oid = int(parts[1])
        ok, order, _, prev, new = update_order_status(
            oid,
            "COMPLETED",
            tenant_id=tenant.id,
            admin_chat_id=message.chat.id if message.chat else None,
            enforce_workflow=True,
        )
        if ok and order and new:
            await notify_order_status_changed(order.id, tenant.id, prev, new)
        await _answer_admin(message, "Yakunlandi." if ok else "Buyurtma topilmadi yoki status noto'g'ri.")

    @router.message(Command("admin"))
    async def admin_login_link(message: types.Message):
        user_id = message.from_user.id if message.from_user else None
        print("ADMIN COMMAND:", user_id)
        if not message.chat or not tenant.admin_chat_id or int(message.chat.id) != int(tenant.admin_chat_id):
            await _answer_admin(message, "Access denied")
            return
        login_token = create_admin_login_token_for_tenant(tenant)
        await _answer_admin(
            message,
            "\n".join(
                [
                    "Admin login link (10 minutes, one-time use):",
                    _admin_menu_url(login_token.token),
                ]
            )
        )

    return router
