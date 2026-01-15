from functools import wraps
from aiogram import Router, types
from aiogram.filters import Command

from src.store import is_admin_chat, set_status

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
    ok = set_status(oid, "approved", admin_chat_id=message.chat.id if message.chat else None)
    await message.answer("Tasdiqlandi ✅") if ok else await message.answer("Buyurtma topilmadi.")


@router.message(Command("reject"))
@admin_only
async def reject(message: types.Message):
    if not message.text:
        return await message.answer("Format: /reject 12")
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        return await message.answer("Format: /reject 12")
    oid = int(parts[1])
    ok = set_status(oid, "rejected", admin_chat_id=message.chat.id if message.chat else None)
    await message.answer("Rad etildi.") if ok else await message.answer("Buyurtma topilmadi.")


@router.message(Command("done"))
@admin_only
async def done(message: types.Message):
    if not message.text:
        return await message.answer("Format: /done 12")
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        return await message.answer("Format: /done 12")
    oid = int(parts[1])
    ok = set_status(oid, "done", admin_chat_id=message.chat.id if message.chat else None)
    await message.answer("Yakunlandi.") if ok else await message.answer("Buyurtma topilmadi.")
