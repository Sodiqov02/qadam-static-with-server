from aiogram import Router, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..menu import Menu
from ..cart import Cart, user_carts
from ..config import load_config

router = Router()
config = load_config()

def get_menu_markup():
    kb = InlineKeyboardBuilder()
    for item in Menu.get_all():
        kb.button(text=f"{item.name} - {item.price} so'm", callback_data=f"add:{item.name}")
    kb.button(text="🛒 Savat", callback_data="cart")
    kb.adjust(1)
    return kb.as_markup()

def get_cart_markup():
    kb = InlineKeyboardBuilder()
    kb.button(text="🔄 Menu", callback_data="menu")
    kb.button(text="✅ Buyurtma berish", callback_data="order")
    kb.adjust(1)
    return kb.as_markup()

@router.message(Command("menu"))
async def show_menu(message: Message):
    text = "🍽 Menu:\n\n"
    for item in Menu.get_all():
        text += f"{item.name} - {item.price} so'm\n"
    await message.answer(text, reply_markup=get_menu_markup())

@router.callback_query(lambda c: c.data == "menu")
async def menu_button(callback: CallbackQuery):
    text = "🍽 Menu:\n\n"
    for item in Menu.get_all():
        text += f"{item.name} - {item.price} so'm\n"
    await callback.message.answer(text, reply_markup=get_menu_markup())
    await callback.answer()

@router.callback_query(lambda c: c.data and c.data.startswith("add:"))
async def add_item(callback: CallbackQuery):
    user_id = callback.from_user.id
    if user_id not in user_carts:
        user_carts[user_id] = Cart()

    item_name = callback.data.split(":")[1]
    item = Menu.get_by_name(item_name)
    if not item:
        await callback.answer("Bu taom mavjud emas")
        return

    user_carts[user_id].add_item(item)
    await callback.answer(f"{item.name} savatga qo'shildi!")

@router.callback_query(lambda c: c.data == "cart")
async def show_cart(callback: CallbackQuery):
    user_id = callback.from_user.id
    if user_id not in user_carts or user_carts[user_id].is_empty():
        await callback.answer("Savatingiz bo'sh!")
        return

    cart = user_carts[user_id]
    items = cart.get_items()
    text = "🛒 Sizning savatchangiz:\n\n"
    total = 0

    for item in items:
        price = item.item.price * item.quantity
        total += price
        text += f"{item.item.name} x{item.quantity} = {price:,} so'm\n"

    text += f"\nJami: {total:,} so'm"
    await callback.message.answer(text, reply_markup=get_cart_markup())
    await callback.answer()

@router.callback_query(lambda c: c.data == "order")
async def process_order(callback: CallbackQuery):
    user_id = callback.from_user.id
    if user_id not in user_carts or user_carts[user_id].is_empty():
        await callback.answer("Savatingiz bo'sh!")
        return

    cart = user_carts[user_id]
    items = cart.get_items()
    order_text = "🚀 Yangi buyurtma!\n\n"
    total = 0

    for item in items:
        price = item.item.price * item.quantity
        total += price
        order_text += f"{item.item.name} x{item.quantity} = {price:,} so'm\n"

    order_text += f"\nJami: {total:,} so'm"

    # Отправляем заказ админу
    await callback.bot.send_message(config["ADMIN_ID"], order_text)

    # Очищаем корзину
    cart.clear()

    # Сообщаем пользователю
    await callback.message.answer("✅ Buyurtmangiz qabul qilindi! Tez orada siz bilan bog'lanamiz.")
    await callback.answer("Buyurtma yuborildi!")

router = Router(name=__name__)

def get_menu_keyboard(user_id: int | None = None):
    """Generate keyboard for menu"""
    builder = InlineKeyboardBuilder()
    for item in Menu.get_all():
        builder.button(
            text=f"{item.name} - {item.price:,} so'm",
            callback_data=f"add:{item.name}"
        )
    builder.button(text="🛒 Savat", callback_data="cart")
    # Показываем кнопку "Заказать" только если корзина не пуста
    if user_id and user_id in user_carts and not user_carts[user_id].is_empty():
        builder.button(text="🚚 Buyurtma berish", callback_data="checkout")
    builder.adjust(1)  # One button per row
    return builder.as_markup()

def get_cart_keyboard(cart: Cart):
    """Generate keyboard for cart"""
    builder = InlineKeyboardBuilder()
    for cart_item in cart.get_items():
        builder.button(
            text=f"❌ {cart_item.item.name}",
            callback_data=f"remove:{cart_item.item.name}"
        )
    builder.button(text="🔄 Menu", callback_data="menu")
    builder.button(text="🚚 Buyurtma berish", callback_data="checkout")
    builder.adjust(1)
    return builder.as_markup()

@router.message(Command("menu"))
async def show_menu(message: Message):
    """Show menu command handler"""
    text = "🍽 Menu:\n\n"
    for item in Menu.get_all():
        text += f"• {item.name} - {item.price:,} so'm\n"
        if item.description:
            text += f"  {item.description}\n"
    
    try:
        await message.answer(
            text,
            reply_markup=get_menu_keyboard(message.from_user.id if message.from_user else None)
        )
    except TelegramBadRequest as e:
        print(f"Error in show_menu: {e}")

@router.callback_query(lambda c: c.data == "menu")
async def show_menu_callback(callback: CallbackQuery):
    """Menu button handler"""
    if not callback.message:
        await callback.answer("Xatolik yuz berdi. Iltimos /menu buyrug'ini qayta yuboring.")
        return

    text = "🍽 Menu:\n\n"
    for item in Menu.get_all():
        text += f"• {item.name} - {item.price:,} so'm\n"
        if item.description:
            text += f"  {item.description}\n"
    
    try:
        await callback.message.edit_text(
            text,
            reply_markup=get_menu_keyboard(callback.from_user.id if callback.from_user else None)
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            print(f"Error in show_menu_callback: {e}")
            try:
                await callback.message.answer(
                    text,
                    reply_markup=get_menu_keyboard(callback.from_user.id if callback.from_user else None)
                )
            except TelegramBadRequest as e2:
                print(f"Error sending new message: {e2}")
    
    await callback.answer()

@router.callback_query(lambda c: c.data and c.data.startswith('add:'))
async def add_to_cart(callback: CallbackQuery):
    """Add item to cart handler"""
    if not callback.from_user or not callback.message:
        await callback.answer("Xatolik yuz berdi")
        return

    user_id = callback.from_user.id
    if user_id not in user_carts:
        user_carts[user_id] = Cart()
    
    if not callback.data:
        await callback.answer("Ma'lumot topilmadi")
        return
    
    item_name = callback.data.split(':')[1]
    item = Menu.get_by_name(item_name)
    if not item:
        await callback.answer("Kechirasiz, bu taom endi mavjud emas")
        return

    cart = user_carts[user_id]
    cart.add_item(item)
    
    try:
        text = f"🍽 Menu:\n\n" + "\n".join(
            f"• {item.name} - {item.price:,} so'm\n  {item.description}"
            for item in Menu.get_all()
        ) + f"\n\n🛒 Savatingizda: {cart.get_total():,} so'm"
        
        await callback.message.edit_text(
            text,
            reply_markup=get_menu_keyboard(user_id)
        )
        await callback.answer(f"✅ {item.name} savatga qo'shildi!")
    except TelegramBadRequest as e:
        print(f"Error in add_to_cart: {e}")
        await callback.answer("Xatolik yuz berdi")

@router.callback_query(lambda c: c.data == 'cart')
async def show_cart(callback: CallbackQuery):
    """Show cart handler"""
    if not callback.from_user or not callback.message:
        await callback.answer("Xatolik yuz berdi")
        return

    user_id = callback.from_user.id
    if user_id not in user_carts or user_carts[user_id].is_empty():
        await callback.answer("Savatingiz bo'sh!")
        try:
            await callback.message.edit_text(
                "Savatingiz bo'sh!\n\nMenuga qaytamizmi?",
                reply_markup=get_menu_keyboard(user_id)
            )
        except TelegramBadRequest as e:
            print(f"Error in show_cart: {e}")
        return

    cart = user_carts[user_id]
    total = cart.get_total()
    items_text = "\n".join(
        f"• {item.item.name} x{item.quantity} = {item.item.price * item.quantity:,} so'm"
        for item in cart.get_items()
    )
    
    try:
        await callback.message.edit_text(
            f"🛒 Savatingiz:\n\n{items_text}\n\nJami: {total:,} so'm",
            reply_markup=get_cart_keyboard(cart)
        )
    except TelegramBadRequest as e:
        print(f"Error in show_cart: {e}")
        try:
            await callback.message.answer(
                f"🛒 Savatingiz:\n\n{items_text}\n\nJami: {total:,} so'm",
                reply_markup=get_cart_keyboard(cart)
            )
        except TelegramBadRequest as e2:
            print(f"Error sending new message in show_cart: {e2}")
    
    await callback.answer()

@router.callback_query(lambda c: c.data == 'checkout')
async def checkout(callback: CallbackQuery):
    """Checkout handler"""
    if not callback.from_user or not callback.message:
        await callback.answer("Xatolik yuz berdi")
        return

    user_id = callback.from_user.id
    if user_id not in user_carts or user_carts[user_id].is_empty():
        await callback.answer("Savatingiz bo'sh!")
        return

    cart = user_carts[user_id]
    items = [
        f"• {item.item.name} x{item.quantity} = {item.item.price * item.quantity:,} so'm"
        for item in cart.get_items()
    ]
    
    text = "\n".join([
        "📝 Buyurtma berish uchun quyidagi formatda yozing:",
        "",
        "Ism: <ism>",
        "Tel: <telefon>",
        "Manzil: <manzil>",
        "",
        "Sizning buyurtmangiz:",
        *items,
        "",
        f"Jami: {cart.get_total():,} so'm"
    ])

    try:
        await callback.message.answer(text)
        # Очищаем корзину после оформления заказа
        cart.clear()
        await callback.answer("Buyurtma formasi yuborildi!")
    except TelegramBadRequest as e:
        print(f"Error in checkout: {e}")
        await callback.answer("Xatolik yuz berdi. Iltimos qaytadan urinib ko'ring.")
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest

from typing import cast, Union, Optional
from ..menu import Menu
from ..cart import Cart, user_carts

router = Router(name=__name__)

def get_menu_keyboard(user_id: int | None = None):
    builder = InlineKeyboardBuilder()
    for item in Menu.get_all():
        builder.button(
            text=f"{item.name} - {item.price:,} so'm",
            callback_data=f"add:{item.name}"
        )
    builder.button(text="🛒 Savat", callback_data="cart")
    # Показываем кнопку "Заказать" только если корзина не пуста
    if user_id and user_id in user_carts and not user_carts[user_id].is_empty():
        builder.button(text="🚚 Buyurtma berish", callback_data="checkout")
    builder.adjust(1)  # One button per row
    return builder.as_markup()

def get_cart_keyboard(cart: Cart):
    builder = InlineKeyboardBuilder()
    for cart_item in cart.get_items():
        builder.button(
            text=f"❌ {cart_item.item.name}",
            callback_data=f"remove:{cart_item.item.name}"
        )
    builder.button(text="🔄 Menu", callback_data="menu")
    builder.button(text="🚚 Buyurtma berish", callback_data="checkout")
    builder.adjust(1)
    return builder.as_markup()

@router.message(Command("menu"))
async def show_menu(message: Message):
    text = "🍽 Menu:\n\n"
    for item in Menu.get_all():
        text += f"• {item.name} - {item.price:,} so'm\n"
        if item.description:
            text += f"  {item.description}\n"
    
    await message.answer(
        text,
        reply_markup=get_menu_keyboard(message.from_user.id if message.from_user else None)
    )

@router.callback_query(lambda c: c.data == "menu")
async def show_menu_callback(callback: CallbackQuery):
    if not callback.message:
        await callback.answer("Xatolik yuz berdi. Iltimos /menu buyrug'ini qayta yuboring.")
        return

    text = "🍽 Menu:\n\n"
    for item in Menu.get_all():
        text += f"• {item.name} - {item.price:,} so'm\n"
        if item.description:
            text += f"  {item.description}\n"
    
    try:
        if callback.message:
            await callback.message.edit_text(
                text,
                reply_markup=get_menu_keyboard(callback.from_user.id if callback.from_user else None),
                parse_mode=ParseMode.HTML
            )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            if callback.message:
                await callback.message.answer(
                    text,
                    reply_markup=get_menu_keyboard(callback.from_user.id if callback.from_user else None),
                    parse_mode=ParseMode.HTML
                )
    
    await callback.answer()

@router.callback_query(lambda c: c.data and c.data.startswith('add:'))
async def add_to_cart(callback: CallbackQuery):
    if not callback.from_user:
        await callback.answer("Foydalanuvchi ma'lumotlari topilmadi")
        return

    if not callback.message:
        await callback.answer("Xabar ma'lumotlari topilmadi")
        return

    user_id = callback.from_user.id
    if user_id not in user_carts:
        user_carts[user_id] = Cart()
    
    if not callback.data:
        await callback.answer("Ma'lumot topilmadi")
        return
    
    item_name = callback.data.split(':')[1]
    item = Menu.get_by_name(item_name)
    if not item:
        await callback.answer("Kechirasiz, bu taom endi mavjud emas")
        return
    
    user_carts[user_id].add_item(item)
    await callback.answer(f"✅ {item.name} savatga qo'shildi!")
    
    cart = user_carts[user_id]
    total = cart.get_total()
    items_text = "\n".join(
        f"• {item.item.name} x{item.quantity} = {item.item.price * item.quantity:,} so'm"
        for item in cart.get_items()
    )
    
    # Обновляем текущее сообщение вместо отправки нового
    if callback.message:
        await callback.message.edit_text(
            f"🍽 Menu:\n\n" + "\n".join(
                f"• {item.name} - {item.price:,} so'm\n  {item.description}"
                for item in Menu.get_all()
            ) + f"\n\n🛒 Savatingizda: {total:,} so'm",
            reply_markup=get_menu_keyboard(callback.from_user.id if callback.from_user else None)
        )

@router.callback_query(lambda c: c.data and c.data.startswith('remove:'))
async def remove_from_cart(callback: CallbackQuery):
    if not callback.from_user:
        await callback.answer("Foydalanuvchi ma'lumotlari topilmadi")
        return

    if not callback.message:
        await callback.answer("Xabar ma'lumotlari topilmadi")
        return

    user_id = callback.from_user.id
    if user_id not in user_carts:
        await callback.answer("Savatingiz bo'sh!")
        return
    
    if not callback.data:
        await callback.answer("Ma'lumot topilmadi")
        return

    item_name = callback.data.split(':')[1]
    cart = user_carts[user_id]
    cart.remove_item(item_name)
    
    if cart.is_empty():
        await callback.message.edit_text(
            "Savatingiz bo'sh!\n\nMenuga qaytamizmi?",
            reply_markup=get_menu_keyboard()
        )
    else:
        total = cart.get_total()
        items_text = "\n".join(
            f"• {item.item.name} x{item.quantity} = {item.item.price * item.quantity:,} so'm"
            for item in cart.get_items()
        )
        await callback.message.edit_text(
            f"🛒 Savatingiz:\n\n{items_text}\n\nJami: {total:,} so'm",
            reply_markup=get_cart_keyboard(cart)
        )
    
    await callback.answer(f"{item_name} savatdan olib tashlandi")

@router.callback_query(lambda c: c.data == 'cart')
async def show_cart(callback: CallbackQuery):
    user_id = callback.from_user.id
    if user_id not in user_carts or user_carts[user_id].is_empty():
        await callback.answer("Savatingiz bo'sh!")
        return

    cart = user_carts[user_id]
    total = cart.get_total()
    items_text = "\n".join(
        f"• {item.item.name} x{item.quantity} = {item.item.price * item.quantity:,} so'm"
        for item in cart.get_items()
    )
    
    await callback.message.edit_text(
        f"🛒 Savatingiz:\n\n{items_text}\n\nJami: {total:,} so'm",
        reply_markup=get_cart_keyboard(cart)
    )
    await callback.answer()

@router.callback_query(lambda c: c.data == 'checkout')
async def checkout(callback: CallbackQuery):
    """Handle checkout process"""
    if not callback.from_user or not callback.message:
        await callback.answer("Xatolik yuz berdi")
        return

    user_id = callback.from_user.id
    if user_id not in user_carts or user_carts[user_id].is_empty():
        await callback.answer("Savatingiz bo'sh!")
        return

    cart = user_carts[user_id]
    items = []
    for item in cart.get_items():
        items.append(f"• {item.item.name} x{item.quantity} = {item.item.price * item.quantity:,} so'm")

    text = "📝 Buyurtma berish uchun quyidagi formatda yozing:\n\n"
    text += "Ism: <ism>\n"
    text += "Tel: <telefon>\n"
    text += "Manzil: <manzil>\n\n"
    text += "Sizning buyurtmangiz:\n"
    text += "\n".join(items)
    text += f"\n\nJami: {cart.get_total():,} so'm"

    await callback.message.answer(text)
    # Очищаем корзину после оформления заказа
    cart.clear()
    await callback.answer("Buyurtma formasi yuborildi!")