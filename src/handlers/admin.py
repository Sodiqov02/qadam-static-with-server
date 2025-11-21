from functools import wraps
from aiogram import Router, types
from aiogram.filters import Command

from src.config import settings
from src.store import set_status

router = Router()


def admin_only(func):
    @wraps(func)
    async def wrapper(message: types.Message, *args, **kwargs):
        if message.chat.id != settings.ADMIN_CHAT_ID:
            return
        return await func(message, *args, **kwargs)

    return wrapper


@router.message(Command("approve"))
@admin_only
async def approve(message: types.Message):
    if not message.text:
        return await message.answer("Формат: /approve 12")
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        return await message.answer("Формат: /approve 12")
    oid = int(parts[1])
    ok = set_status(oid, "approved")
    await message.answer("Готово") if ok else await message.answer("Заказ не найден")


@router.message(Command("reject"))
@admin_only
async def reject(message: types.Message):
    if not message.text:
        return await message.answer("Формат: /reject 12")
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        return await message.answer("Формат: /reject 12")
    oid = int(parts[1])
    ok = set_status(oid, "rejected")
    await message.answer("Отклонено") if ok else await message.answer("Заказ не найден")


@router.message(Command("done"))
@admin_only
async def done(message: types.Message):
    if not message.text:
        return await message.answer("Формат: /done 12")
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        return await message.answer("Формат: /done 12")
    oid = int(parts[1])
    ok = set_status(oid, "done")
    await message.answer("Выполнено") if ok else await message.answer("Заказ не найден")
