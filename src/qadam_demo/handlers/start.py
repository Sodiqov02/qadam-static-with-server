from aiogram import Router, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

router = Router(name=__name__)

def get_start_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="🍽 Menu", callback_data="menu")
    builder.button(text="🛒 Savat", callback_data="cart")
    builder.button(text="🚚 Buyurtma berish", callback_data="checkout")
    builder.button(text="ℹ️ Yordam", callback_data="help")
    builder.adjust(2)  # Two buttons per row
    return builder.as_markup()

@router.message(Command("start"))
@router.message(Command("help"))
async def start_cmd(message: types.Message):
    args = message.text.split()[1:] if message.text else []
    data = args[0] if args else ""
    
    commands_help = (
        "Bot buyruqlari:\n"
        "/start - Botni ishga tushirish\n"
        "/menu - Taomlar menyusi\n"
        "/cart - Savatchani ko'rish\n"
        "/help - Yordam"
    )
    
    await message.answer(
        f"Assalomu alaykum! 👋\n\n"
        f"«Qadam» xizmatiga xush kelibsiz!\n\n"
        f"{commands_help}\n\n"
        f"Buyurtma berish uchun «Menu» tugmasini bosing 👇"
        + (f"\n\nBuyurtma: {data} ✅" if data else ""),
        reply_markup=get_start_keyboard()
    )

@router.callback_query(lambda c: c.data == "help")
async def help_callback(callback: types.CallbackQuery):
    await start_cmd(callback.message)
    await callback.answer()