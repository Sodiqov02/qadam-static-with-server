import httpx
from aiogram import Router, types
from aiogram.filters import Command
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from src.config import settings

router = Router()

class Checkout(StatesGroup):
    name = State()
    phone = State()
    address = State()
    comment = State()

@router.message(Command("start"))
async def start(message: types.Message):
    await message.answer("Привет! /menu — показать меню, /cart — оформить примерный заказ.")

@router.message(Command("menu"))
async def show_menu(message: types.Message):
    async with httpx.AsyncClient() as cx:
        r = await cx.get(f"{settings.API_BASE_URL}/menu", timeout=10)
        r.raise_for_status()
        data = r.json()
    lines = []
    for cat in data["categories"]:
        lines.append(f"🍽 <b>{cat['title']}</b>")
        for it in cat["items"]:
            lines.append(f"• {it['name']} — {it['price']} сум (id: <code>{it['id']}</code>)")
    lines.append("\nДобавь в корзину командой: /add item_id qty\nНапр.: /add pepperoni 2")
    await message.answer("\n".join(lines))

@router.message(Command("add"))
async def add_to_cart(message: types.Message, state: FSMContext):
    try:
        _, item_id, qty = message.text.split()
        qty = int(qty)
    except Exception:
        return await message.answer("Формат: /add item_id qty")
    data = await state.get_data()
    cart = data.get("cart", {})
    cart[item_id] = cart.get(item_id, 0) + qty
    await state.update_data(cart=cart)
    await message.answer(f"Добавил: {item_id} x{qty}\n/cart — оформить")

@router.message(Command("cart"))
async def cart_checkout(message: types.Message, state: FSMContext):
    data = await state.get_data()
    cart = data.get("cart", {})
    if not cart:
        return await message.answer("Корзина пустая. /menu чтобы выбрать.")
    lines = ["🧺 <b>Корзина</b>"]
    for k, v in cart.items():
        lines.append(f"- {k} x{v}")
    lines.append("\nТеперь введём данные. Как вас зовут?")
    await message.answer("\n".join(lines))
    await state.set_state(Checkout.name)

@router.message(Checkout.name)
async def get_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("Телефон?")
    await state.set_state(Checkout.phone)

@router.message(Checkout.phone)
async def get_phone(message: types.Message, state: FSMContext):
    await state.update_data(phone=message.text)
    await message.answer("Адрес доставки?")
    await state.set_state(Checkout.address)

@router.message(Checkout.address)
async def get_address(message: types.Message, state: FSMContext):
    await state.update_data(address=message.text)
    await message.answer("Комментарий? (или напишите - )")
    await state.set_state(Checkout.comment)

@router.message(Checkout.comment)
async def finish_order(message: types.Message, state: FSMContext):
    data = await state.get_data()
    cart = data.get("cart", {})
    comment = None if message.text.strip() == "-" else message.text.strip()

    payload = {
        "items": [{"item_id": k, "qty": v} for k, v in cart.items()],
        "customer": {
            "name": data.get("name",""),
            "phone": data.get("phone",""),
            "address": data.get("address",""),
            "comment": comment
        },
        "source": "bot"
    }
    async with httpx.AsyncClient() as cx:
        r = await cx.post(f"{settings.API_BASE_URL}/orders", json=payload, timeout=10)
        r.raise_for_status()
        order = r.json()

    await state.clear()
    await message.answer(f"✅ Заказ оформлен! Номер #{order['order_id']}. Ждите звонка.")
