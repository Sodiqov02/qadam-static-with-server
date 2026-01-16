import asyncio
import httpx
from aiogram import Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from src.bot_init import get_bot
from src.config import settings
from src.store import DEFAULT_TENANT_SLUG, get_user_tenant, set_user_tenant

router = Router()

# In-memory carts: user_id -> {item_id: qty}
user_carts: dict[int, dict[str, int]] = {}
# In-memory tenant cache to avoid DB round-trips on every message
user_tenants_cache: dict[int, str] = {}


class Checkout(StatesGroup):
    name = State()
    phone = State()
    address = State()
    comment = State()


def _main_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Menyu"), KeyboardButton(text="Savat")], [KeyboardButton(text="Tozalash")]],
        resize_keyboard=True,
    )


async def _safe_delete_message(message: types.Message | None) -> None:
    if not message:
        return
    try:
        await message.delete()
    except Exception:
        return


async def _remember_tenant(user_id: int, slug: str):
    user_tenants_cache[user_id] = slug
    await asyncio.to_thread(set_user_tenant, user_id, slug)


async def _get_tenant_slug(user_id: int) -> str | None:
    if user_id in user_tenants_cache:
        return user_tenants_cache[user_id]
    tenant = await asyncio.to_thread(get_user_tenant, user_id)
    if tenant and getattr(tenant, "slug", None):
        user_tenants_cache[user_id] = tenant.slug
        return tenant.slug
    await _remember_tenant(user_id, DEFAULT_TENANT_SLUG)
    return DEFAULT_TENANT_SLUG


async def _require_tenant_slug(message: types.Message) -> str | None:
    if not message.from_user:
        return None
    return await _get_tenant_slug(message.from_user.id)


async def _load_menu(slug: str) -> dict:
    base_url = (settings.API_BASE_URL or "").rstrip("/")
    if base_url.endswith("/api"):
        base_url = base_url[:-4]
    if not base_url:
        raise RuntimeError("API_BASE_URL is not configured")
    async with httpx.AsyncClient() as cx:
        r = await cx.get(f"{base_url}/t/{slug}/menu", timeout=10)
        r.raise_for_status()
        return r.json()


def _item_map(menu: dict) -> dict[str, dict]:
    mapper: dict[str, dict] = {}
    for cat in menu.get("categories", []):
        for it in cat.get("items", []):
            mapper[str(it.get("id"))] = it
    return mapper


def _cart_for(uid: int) -> dict[str, int]:
    return user_carts.setdefault(uid, {})


def _menu_keyboard(menu: dict) -> InlineKeyboardMarkup:
    buttons = []
    for cat in menu.get("categories", []):
        for it in cat.get("items", []):
            text = f"{it.get('name')} - {it.get('price')} so'm"
            buttons.append([InlineKeyboardButton(text=text[:64], callback_data=f"add:{it.get('id')}")])
    buttons.append(
        [
            InlineKeyboardButton(text="Savat", callback_data="cart"),
            InlineKeyboardButton(text="Tozalash", callback_data="clear"),
            InlineKeyboardButton(text="Buyurtma berish", callback_data="checkout"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _cart_keyboard(cart: dict[str, int]) -> InlineKeyboardMarkup:
    buttons = []
    for item_id, qty in cart.items():
        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"- {item_id} x{qty}",
                    callback_data=f"remove:{item_id}",
                )
            ]
        )
    buttons.append(
        [
            InlineKeyboardButton(text="Menyu", callback_data="menu"),
            InlineKeyboardButton(text="Buyurtma berish", callback_data="checkout"),
            InlineKeyboardButton(text="Tozalash", callback_data="clear"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _cart_text(cart: dict[str, int], items: dict[str, dict]) -> str:
    if not cart:
        return "Savat bo'sh."
    lines = ["Savatingiz:", ""]
    total = 0
    for item_id, qty in cart.items():
        meta = items.get(item_id, {})
        name = meta.get("name", item_id)
        price = int(meta.get("price") or 0)
        line_total = price * qty if price else qty
        total += line_total
        lines.append(f"- {name} x{qty} = {line_total} so'm")
    lines.append(f"\nJami: {total} so'm")
    lines.append("\nBuyurtma berish tugmasini bosing.")
    return "\n".join(lines)


@router.message(Command("start"))
async def start(message: types.Message):
    slug = None
    if message.text:
        parts = message.text.split(maxsplit=1)
        if len(parts) == 2:
            slug = parts[1].strip()
    if message.from_user:
        await _remember_tenant(message.from_user.id, slug or DEFAULT_TENANT_SLUG)
    if slug:
        await message.answer(f"Tugallandi. Tanlangan filial: {slug}", reply_markup=_main_kb())
    else:
        await message.answer(
            f"Salom! Demo menyu yoqildi: {DEFAULT_TENANT_SLUG}. "
            "Menyu / savat / tozalash uchun tugmalarni ishlating.",
            reply_markup=_main_kb(),
        )
    await _safe_delete_message(message)


@router.message(Command("tenant"))
async def set_tenant(message: types.Message):
    if not message.text or len(message.text.split()) != 2:
        await message.answer("Format: /tenant <slug>")
        await _safe_delete_message(message)
        return
    slug = message.text.split()[1]
    if message.from_user:
        await _remember_tenant(message.from_user.id, slug)
    await message.answer(f"Tenant tanlandi: {slug}", reply_markup=_main_kb())
    await _safe_delete_message(message)


@router.message(Command("menu"))
@router.message(lambda m: m.text and m.text.lower() in {"menu", "menyu"})
async def show_menu(message: types.Message):
    if not message.from_user:
        return
    slug = await _require_tenant_slug(message)
    if not slug:
        return
    try:
        menu = await _load_menu(slug)
    except Exception:
        await message.answer("Menyu vaqtincha mavjud emas. Keyinroq urinib ko'ring.")
        await _safe_delete_message(message)
        return
    lines = []
    for cat in menu.get("categories", []):
        lines.append(f"[{cat.get('title','')}]")
        for it in cat.get("items", []):
            lines.append(f"- {it.get('name')} - {it.get('price')} so'm (id: {it.get('id')})")
        lines.append("")
    await message.answer("\n".join(lines), reply_markup=_menu_keyboard(menu))
    await _safe_delete_message(message)


@router.callback_query(lambda c: c.data == "menu")
async def menu_callback(callback: CallbackQuery):
    if not callback.from_user:
        return await callback.answer("Foydalanuvchi aniqlanmadi", show_alert=True)
    slug = await _get_tenant_slug(callback.from_user.id)
    if not slug:
        return await callback.answer("Avval /start <slug>", show_alert=True)
    try:
        menu = await _load_menu(slug)
    except Exception:
        await callback.answer("Menyu mavjud emas", show_alert=True)
        return
    text_lines = []
    for cat in menu.get("categories", []):
        text_lines.append(f"[{cat.get('title','')}]")
        for it in cat.get("items", []):
            text_lines.append(f"- {it.get('name')} - {it.get('price')} so'm (id: {it.get('id')})")
        text_lines.append("")
    await callback.message.edit_text("\n".join(text_lines), reply_markup=_menu_keyboard(menu))
    await callback.answer()


@router.callback_query(lambda c: c.data == "cart")
async def cart_callback(callback: CallbackQuery, state: FSMContext):
    if not callback.from_user or not callback.message:
        return await callback.answer("Foydalanuvchi aniqlanmadi", show_alert=True)
    slug = await _get_tenant_slug(callback.from_user.id)
    if not slug:
        return await callback.answer("Avval /start <slug>", show_alert=True)
    user_id = callback.from_user.id
    cart = _cart_for(user_id)
    try:
        menu = await _load_menu(slug)
    except Exception:
        return await callback.answer("Menyu mavjud emas", show_alert=True)
    items = _item_map(menu)
    if not cart:
        await callback.answer("Savat bo'sh", show_alert=True)
        return await callback.message.edit_text("Savat bo'sh. Menyu tugmasini bosing.")
    await state.update_data(cart=cart, tenant_slug=slug)
    await callback.message.edit_text(_cart_text(cart, items), reply_markup=_cart_keyboard(cart))
    await callback.answer()


@router.message(Command("add"))
async def add_to_cart_manual(message: types.Message):
    if not message.from_user:
        return
    slug = await _require_tenant_slug(message)
    if not slug:
        return
    try:
        _, item_id, qty = message.text.split()
        qty = int(qty)
    except Exception:
        await message.answer("Format: /add item_id qty")
        await _safe_delete_message(message)
        return
    cart = _cart_for(message.from_user.id)
    cart[item_id] = cart.get(item_id, 0) + qty
    await message.answer(f"Qo'shildi: {item_id} x{qty}\n/cart - savatni ko'rish", reply_markup=_main_kb())
    await _safe_delete_message(message)


@router.callback_query(lambda c: c.data and c.data.startswith("add:"))
async def add_to_cart(callback: CallbackQuery):
    if not callback.from_user:
        return await callback.answer("Foydalanuvchi aniqlanmadi", show_alert=True)
    item_id = callback.data.split(":", 1)[1]
    cart = _cart_for(callback.from_user.id)
    cart[item_id] = cart.get(item_id, 0) + 1
    await callback.answer("Savatga qo'shildi")


@router.message(Command("clear"))
@router.message(lambda m: m.text and m.text.lower() == "tozalash")
async def clear_cart_cmd(message: types.Message):
    if message.from_user:
        user_carts.pop(message.from_user.id, None)
    await message.answer("Savat tozalandi.", reply_markup=_main_kb())
    await _safe_delete_message(message)


@router.callback_query(lambda c: c.data == "clear")
async def clear_cart_callback(callback: CallbackQuery):
    if callback.from_user:
        user_carts.pop(callback.from_user.id, None)
    await callback.answer("Savat tozalandi")
    await callback.message.edit_text("Savat bo'sh.")


@router.message(Command("cart"))
@router.message(lambda m: m.text and m.text.lower() == "savat")
async def cart_checkout(message: types.Message, state: FSMContext):
    if not message.from_user:
        return await message.answer("Foydalanuvchini aniqlab bo'lmadi.")
    slug = await _require_tenant_slug(message)
    if not slug:
        return
    user_id = message.from_user.id
    cart = _cart_for(user_id)
    menu = await _load_menu(slug)
    items = _item_map(menu)
    if not cart:
        await message.answer("Savat bo'sh. Menyu tugmasini bosing.", reply_markup=_main_kb())
        await _safe_delete_message(message)
        return

    await state.update_data(cart=cart, tenant_slug=slug)
    await message.answer(
        _cart_text(cart, items),
        reply_markup=_cart_keyboard(cart),
    )
    await state.set_state(Checkout.name)
    await message.answer("Ismingizni yozing:", reply_markup=_main_kb())
    await _safe_delete_message(message)


@router.callback_query(lambda c: c.data and c.data.startswith("remove:"))
async def remove_item(callback: CallbackQuery):
    if not callback.from_user:
        return await callback.answer("Foydalanuvchi aniqlanmadi", show_alert=True)
    slug = await _get_tenant_slug(callback.from_user.id)
    if not slug:
        return await callback.answer("Avval /start <slug>", show_alert=True)
    item_id = callback.data.split(":", 1)[1]
    cart = _cart_for(callback.from_user.id)
    cart.pop(item_id, None)
    menu = await _load_menu(slug)
    items = _item_map(menu)
    text = _cart_text(cart, items)
    await callback.message.edit_text(text, reply_markup=_cart_keyboard(cart))
    await callback.answer("O'chirildi")


@router.callback_query(lambda c: c.data == "checkout")
async def checkout_callback(callback: CallbackQuery, state: FSMContext):
    if not callback.from_user or not callback.message:
        return await callback.answer("Foydalanuvchi aniqlanmadi", show_alert=True)
    slug = await _get_tenant_slug(callback.from_user.id)
    if not slug:
        return await callback.answer("Avval /start <slug>", show_alert=True)
    user_id = callback.from_user.id
    cart = _cart_for(user_id)
    menu = await _load_menu(slug)
    items = _item_map(menu)
    if not cart:
        await callback.answer("Savat bo'sh", show_alert=True)
        return await callback.message.edit_text("Savat bo'sh. Menyu tugmasini bosing.")

    await state.update_data(cart=cart, tenant_slug=slug)
    await state.set_state(Checkout.name)
    await callback.message.edit_text(_cart_text(cart, items), reply_markup=_cart_keyboard(cart))
    bot = get_bot()
    if bot:
        await bot.send_message(user_id, "Ismingizni yozing:", reply_markup=_main_kb())
    await callback.answer()


@router.message(Checkout.name)
async def get_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text or "")
    await message.answer("Telefon raqamingiz-")
    await state.set_state(Checkout.phone)
    await _safe_delete_message(message)


@router.message(Checkout.phone)
async def get_phone(message: types.Message, state: FSMContext):
    await state.update_data(phone=message.text or "")
    await message.answer("Manzil-")
    await state.set_state(Checkout.address)
    await _safe_delete_message(message)


@router.message(Checkout.address)
async def get_address(message: types.Message, state: FSMContext):
    await state.update_data(address=message.text or "")
    await message.answer("Izoh (yo'q bo'lsa - '-' yuboring):")
    await state.set_state(Checkout.comment)
    await _safe_delete_message(message)


@router.message(Checkout.comment)
async def finish_order(message: types.Message, state: FSMContext):
    user_id = message.from_user.id if message.from_user else None
    data = await state.get_data()
    cart = user_carts.get(user_id, {}) if user_id else data.get("cart", {})
    if not cart:
        await state.clear()
        await message.answer("Savat bo'sh. Yangi buyurtma uchun Menyu.", reply_markup=_main_kb())
        await _safe_delete_message(message)
        return

    slug = data.get("tenant_slug")
    if not slug and user_id:
        slug = await _get_tenant_slug(user_id)
    if not slug:
        await state.clear()
        await message.answer("Filial tanlanmagan. /start <slug> ni yuboring.")
        await _safe_delete_message(message)
        return

    menu = await _load_menu(slug)
    items = _item_map(menu)
    comment = "-" if not message.text or message.text.strip() == "-" else message.text.strip()

    payload = {
        "items": [{"item_id": k, "qty": v} for k, v in cart.items()],
        "customer": {
            "name": data.get("name", ""),
            "phone": data.get("phone", ""),
            "address": data.get("address", ""),
            "comment": comment,
        },
        "source": "bot",
    }
    base_url = (settings.API_BASE_URL or "").rstrip("/")
    if base_url.endswith("/api"):
        base_url = base_url[:-4]
    async with httpx.AsyncClient() as cx:
        r = await cx.post(f"{base_url}/t/{slug}/orders", json=payload, timeout=10)
        r.raise_for_status()
        order = r.json()

    try:
        total = 0
        item_lines = []
        for item_id, qty in cart.items():
            meta = items.get(item_id, {})
            name = meta.get("name", item_id)
            price = int(meta.get("price") or 0)
            line_total = price * qty if price else qty
            total += line_total
            item_lines.append(f"- {name} x{qty} = {line_total} so'm")
        admin_text = "\n".join(
            [
                f"Yangi buyurtma (bot) #{order.get('order_id')} [{slug}]",
                *item_lines,
                f"Jami: {total} so'm",
                "",
                f"Ism: {data.get('name','')}",
                f"Tel: {data.get('phone','')}",
                f"Manzil: {data.get('address','')}",
                f"Izoh: {comment}",
            ]
        )
        bot = get_bot()
        if bot and settings.ADMIN_CHAT_ID:
            await bot.send_message(chat_id=settings.ADMIN_CHAT_ID, text=admin_text)
    except Exception:
        pass

    if user_id:
        user_carts.pop(user_id, None)
    await state.clear()
    await message.answer(
        f"Rahmat! Buyurtma #{order['order_id']} qabul qilindi.", reply_markup=_main_kb()
    )
    await _safe_delete_message(message)
