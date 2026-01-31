from functools import wraps
from aiogram import Router, types
from aiogram.filters import Command

from src.notifier import notify_order_status_changed
from src.store import is_admin_chat, update_order_status

router = Router()


def admin_only(func):
    @wraps(func)
    async def wrapper(message: types.Message, *args, **kwargs):
        if not message.chat:
            return
        if not is_admin_chat(message.chat.id):
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
        oid, "ACCEPTED", admin_chat_id=message.chat.id if message.chat else None, enforce_workflow=True
    )
    if ok and order and new:
        await notify_order_status_changed(order.id, prev, new)
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
        oid, "CANCELED", admin_chat_id=message.chat.id if message.chat else None, enforce_workflow=True
    )
    if ok and order and new:
        await notify_order_status_changed(order.id, prev, new)
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
        oid, "COMPLETED", admin_chat_id=message.chat.id if message.chat else None, enforce_workflow=True
    )
    if ok and order and new:
        await notify_order_status_changed(order.id, prev, new)
    await message.answer("Yakunlandi.") if ok else await message.answer("Buyurtma topilmadi yoki status noto'g'ri.")
