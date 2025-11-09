"""Admin handlers module"""
from aiogram import Router, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from ..config import load_config

router = Router(name=__name__)
config = load_config()

@router.message(Command("test_admin"))
async def admin_test(message: types.Message) -> None:
    """Handle test_admin command"""
    if not message.from_user or message.from_user.id != config["ADMIN_ID"]:
        return
        
    builder = InlineKeyboardBuilder()
    builder.button(text="Qabul qilindi", callback_data="ok")
    builder.button(text="Jo'natildi", callback_data="ship")
    builder.adjust(1)
    
    await message.answer(
        "Buyurtma #TEST",
        reply_markup=builder.as_markup()
    )