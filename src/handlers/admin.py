from functools import wraps
from aiogram import Router, types
from aiogram.filters import Command

from src.config import settings
from src.db_models import Tenant
from src.notifier import notify_order_status_changed
from src.store import create_admin_login_token_for_tenant, update_order_status


def create_admin_router(tenant: Tenant) -> Router:
    router = Router()

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

    @router.message(Command("approve"))
    @admin_only
    async def approve(message: types.Message):
        if not message.text:
            return await message.answer("Format: /approve 12")
        parts = message.text.split()
        if len(parts) != 2 or not parts[1].isdigit():
            return await message.answer("Format: /approve 12")
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
        await message.answer("Tasdiqlandi.") if ok else await message.answer("Buyurtma topilmadi yoki status noto'g'ri.")

    @router.message(Command("reject"))
    @admin_only
    async def reject(message: types.Message):
        if not message.text:
            return await message.answer("Format: /reject 12")
        parts = message.text.split()
        if len(parts) != 2 or not parts[1].isdigit():
            return await message.answer("Format: /reject 12")
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
        await message.answer("Rad etildi.") if ok else await message.answer("Buyurtma topilmadi yoki status noto'g'ri.")

    @router.message(Command("done"))
    @admin_only
    async def done(message: types.Message):
        if not message.text:
            return await message.answer("Format: /done 12")
        parts = message.text.split()
        if len(parts) != 2 or not parts[1].isdigit():
            return await message.answer("Format: /done 12")
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
        await message.answer("Yakunlandi.") if ok else await message.answer("Buyurtma topilmadi yoki status noto'g'ri.")

    @router.message(Command("admin"))
    @admin_only
    async def admin_login_link(message: types.Message):
        login_token = create_admin_login_token_for_tenant(tenant)
        await message.answer(
            "\n".join(
                [
                    "Admin login link (10 minutes, one-time use):",
                    _admin_menu_url(login_token.token),
                ]
            )
        )

    return router
