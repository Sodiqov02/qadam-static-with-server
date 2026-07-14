import asyncio
import httpx
from aiogram import Router, types
from aiogram.exceptions import TelegramAPIError
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

from src.config import settings
from src.db_models import Tenant
from src.store import get_menu_item_map_for_tenant


def create_user_router(tenant: Tenant) -> Router:
    router = Router()

    # In-memory carts per tenant bot: user_id -> {item_id: qty}
    user_carts: dict[int, dict[str, int]] = {}
    # In-memory bot message history per user (to delete prompts)
    user_bot_messages: dict[int, list[int]] = {}
    # Keep last N order confirmations per user
    user_order_messages: dict[int, list[int]] = {}
    submitting_orders: set[int] = set()
    MAX_ORDER_HISTORY = 5
    MAX_COMMENT_LENGTH = 2000

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

    def _comment_kb() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="O'tkazib yuborish", callback_data="skip_comment")]]
        )

    async def _safe_delete_message(message: types.Message | None) -> None:
        if not message:
            return
        try:
            await message.delete()
        except TelegramAPIError:
            return

    def _remember_bot_message(user_id: int, message_id: int, *, order_history: bool = False) -> None:
        if order_history:
            items = user_order_messages.setdefault(user_id, [])
            items.append(message_id)
            if len(items) > MAX_ORDER_HISTORY:
                items.pop(0)
            return
        items = user_bot_messages.setdefault(user_id, [])
        items.append(message_id)

    async def _clear_bot_messages(bot, user_id: int) -> None:
        items = user_bot_messages.pop(user_id, [])
        if not items:
            return
        if not bot:
            return
        for mid in items:
            try:
                await bot.delete_message(chat_id=user_id, message_id=mid)
            except TelegramAPIError:
                continue

    async def _load_menu() -> dict:
        base_url = (settings.QADAM_API_BASE_URL or "").rstrip("/")
        if base_url.endswith("/api"):
            base_url = base_url[:-4]
        if not base_url:
            raise RuntimeError("API_BASE_URL is not configured")
        async with httpx.AsyncClient() as cx:
            r = await cx.get(f"{base_url}/t/{tenant.slug}/menu", timeout=10)
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

    def _cart_items(cart: dict[str, int]) -> dict[str, dict]:
        return get_menu_item_map_for_tenant(tenant, cart.keys())

    def _cart_keyboard(cart: dict[str, int], items: dict[str, dict]) -> InlineKeyboardMarkup:
        buttons = []
        for item_id, qty in cart.items():
            item = items.get(item_id)
            if not item:
                continue
            buttons.append(
                [
                    InlineKeyboardButton(
                        text=f"X {item.get('name', item_id)}",
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
            meta = items.get(item_id)
            if not meta:
                continue
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
        if not message.from_user:
            return
        await _clear_bot_messages(message.bot, message.from_user.id)
        sent = await message.answer(
            f"Salom! {tenant.name} boti. Menyu / savat / tozalash uchun tugmalarni ishlating.",
            reply_markup=_main_kb(),
        )
        _remember_bot_message(message.from_user.id, sent.message_id)
        await _safe_delete_message(message)

    @router.message(Command("menu"))
    @router.message(lambda m: m.text and m.text.lower() in {"menu", "menyu"})
    async def show_menu(message: types.Message):
        if not message.from_user:
            return
        try:
            menu = await _load_menu()
        except (RuntimeError, httpx.HTTPError, ValueError):
            sent = await message.answer("Menyu vaqtincha mavjud emas. Keyinroq urinib ko'ring.")
            await _clear_bot_messages(message.bot, message.from_user.id)
            _remember_bot_message(message.from_user.id, sent.message_id)
            await _safe_delete_message(message)
            return
        lines = []
        for cat in menu.get("categories", []):
            lines.append(f"[{cat.get('title','')}]")
            for it in cat.get("items", []):
                lines.append(f"- {it.get('name')} - {it.get('price')} so'm (id: {it.get('id')})")
            lines.append("")
        await _clear_bot_messages(message.bot, message.from_user.id)
        sent = await message.answer("\n".join(lines), reply_markup=_menu_keyboard(menu))
        _remember_bot_message(message.from_user.id, sent.message_id)
        await _safe_delete_message(message)

    @router.callback_query(lambda c: c.data == "menu")
    async def menu_callback(callback: CallbackQuery):
        if not callback.from_user:
            return await callback.answer("Foydalanuvchi aniqlanmadi", show_alert=True)
        try:
            menu = await _load_menu()
        except (RuntimeError, httpx.HTTPError, ValueError):
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
        if not callback.from_user or not  callback.message:
            return await callback.answer("Foydalanuvchi aniqlanmadi", show_alert=True)
        user_id = callback.from_user.id
        cart = _cart_for(user_id)
        items = _cart_items(cart)
        if not cart:
            await callback.answer("Savat bo'sh", show_alert=True)
            return await callback.message.edit_text("Savat bo'sh. Menyu tugmasini bosing.")
        await state.update_data(cart=cart)
        await callback.message.edit_text(_cart_text(cart, items), reply_markup=_cart_keyboard(cart, items))
        await callback.answer()

    @router.message(Command("add"))
    async def add_to_cart_manual(message: types.Message):
        if not message.from_user:
            return
        try:
            _, item_id, qty = message.text.split()
            qty = int(qty)
        except (AttributeError, ValueError):
            sent = await message.answer("Format: /add item_id qty")
            await _clear_bot_messages(message.bot, message.from_user.id)
            _remember_bot_message(message.from_user.id, sent.message_id)
            await _safe_delete_message(message)
            return
        cart = _cart_for(message.from_user.id)
        cart[item_id] = cart.get(item_id, 0) + qty
        items = _cart_items(cart)
        item_name = items.get(item_id, {}).get("name", item_id)
        await _clear_bot_messages(message.bot, message.from_user.id)
        sent = await message.answer(f"Qo'shildi: {item_name} x{qty}\n/cart - savatni ko'rish", reply_markup=_main_kb())
        _remember_bot_message(message.from_user.id, sent.message_id)
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
        await _clear_bot_messages(message.bot, message.from_user.id)
        sent = await message.answer("Savat tozalandi.", reply_markup=_main_kb())
        _remember_bot_message(message.from_user.id, sent.message_id)
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
        user_id = message.from_user.id
        cart = _cart_for(user_id)
        items = _cart_items(cart)
        if not cart:
            await _clear_bot_messages(message.bot, message.from_user.id)
            sent = await message.answer("Savat bo'sh. Menyu tugmasini bosing.", reply_markup=_main_kb())
            _remember_bot_message(message.from_user.id, sent.message_id)
            await _safe_delete_message(message)
            return

        await state.update_data(cart=cart)
        await _clear_bot_messages(message.bot, message.from_user.id)
        sent = await message.answer(
            _cart_text(cart, items),
            reply_markup=_cart_keyboard(cart, items),
        )
        await state.set_state(Checkout.name)
        _remember_bot_message(message.from_user.id, sent.message_id)
        sent = await message.answer("Ismingizni yozing:", reply_markup=_main_kb())
        _remember_bot_message(message.from_user.id, sent.message_id)
        await _safe_delete_message(message)

    @router.callback_query(lambda c: c.data and c.data.startswith("remove:"))
    async def remove_item(callback: CallbackQuery):
        if not callback.from_user:
            return await callback.answer("Foydalanuvchi aniqlanmadi", show_alert=True)
        item_id = callback.data.split(":", 1)[1]
        cart = _cart_for(callback.from_user.id)
        cart.pop(item_id, None)
        items = _cart_items(cart)
        text = _cart_text(cart, items)
        await callback.message.edit_text(text, reply_markup=_cart_keyboard(cart, items))
        await callback.answer("O'chirildi")

    @router.callback_query(lambda c: c.data == "checkout")
    async def checkout_callback(callback: CallbackQuery, state: FSMContext):
        if not callback.from_user or not callback.message:
            return await callback.answer("Foydalanuvchi aniqlanmadi", show_alert=True)
        user_id = callback.from_user.id
        cart = _cart_for(user_id)
        if not cart:
            await callback.answer("Savat bo'sh", show_alert=True)
            return await callback.message.edit_text("Savat bo'sh. Menyu tugmasini bosing.")

        await state.update_data(cart=cart)
        await state.set_state(Checkout.name)
        bot = callback.message.bot
        if bot:
            await bot.send_message(user_id, "Ismingizni yozing:", reply_markup=_main_kb())
        await callback.answer()

    @router.message(Checkout.name)
    async def get_name(message: types.Message, state: FSMContext):
        await state.update_data(name=message.text or "")
        await _clear_bot_messages(message.bot, message.from_user.id)
        sent = await message.answer("Telefon raqamingiz-")
        _remember_bot_message(message.from_user.id, sent.message_id)
        await state.set_state(Checkout.phone)
        await _safe_delete_message(message)

    @router.message(Checkout.phone)
    async def get_phone(message: types.Message, state: FSMContext):
        await state.update_data(phone=message.text or "")
        await _clear_bot_messages(message.bot, message.from_user.id)
        sent = await message.answer("Manzil-")
        _remember_bot_message(message.from_user.id, sent.message_id)
        await state.set_state(Checkout.address)
        await _safe_delete_message(message)

    @router.message(Checkout.address)
    async def get_address(message: types.Message, state: FSMContext):
        await state.update_data(address=message.text or "")
        await _clear_bot_messages(message.bot, message.from_user.id)
        sent = await message.answer(
            "Buyurtmaga izoh\n\n"
            "Istagingizni yozing, masalan:\n"
            "• piyozsiz;\n"
            "• achchiq sous qo'shmang;\n"
            "• oq eshik;\n"
            "• yetib kelganda qo'ng'iroq qiling.\n\n"
            "Izoh kerak bo'lmasa, «O'tkazib yuborish» tugmasini bosing.",
            reply_markup=_comment_kb(),
        )
        _remember_bot_message(message.from_user.id, sent.message_id)
        await state.set_state(Checkout.comment)
        await _safe_delete_message(message)

    async def _submit_order_once(
        message: types.Message, state: FSMContext, user_id: int, comment: str | None
    ) -> None:
        data = await state.get_data()
        cart = user_carts.get(user_id, {})
        if not cart:
            await state.clear()
            await _clear_bot_messages(message.bot, user_id)
            sent = await message.answer("Savat bo'sh. Yangi buyurtma uchun Menyu.", reply_markup=_main_kb())
            _remember_bot_message(user_id, sent.message_id)
            await _safe_delete_message(message)
            return

        items = _cart_items(cart)

        payload = {
            "items": [{"item_id": k, "qty": v} for k, v in cart.items()],
            "customer": {
                "name": data.get("name", ""),
                "phone": data.get("phone", ""),
                "address": data.get("address", ""),
                "comment": comment,
            },
            "source": "bot",
            "customer_chat_id": user_id,
        }
        base_url = (settings.QADAM_API_BASE_URL or "").rstrip("/")
        if base_url.endswith("/api"):
            base_url = base_url[:-4]
        async with httpx.AsyncClient() as cx:
            r = await cx.post(
                f"{base_url}/t/{tenant.slug}/orders",
                json=payload,
                headers={"x-internal-token": settings.ADMIN_SECRET},
                timeout=10,
            )
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
                    f"Yangi buyurtma (bot) #{order.get('order_id')} [{tenant.slug}]",
                    *item_lines,
                    f"Jami: {total} so'm",
                    "",
                    f"Ism: {data.get('name','')}",
                    f"Tel: {data.get('phone','')}",
                    f"Manzil: {data.get('address','')}",
                    f"Izoh: {comment or '-'}",
                ]
            )
            bot = message.bot
            if bot and tenant.admin_chat_id:
                await bot.send_message(chat_id=int(tenant.admin_chat_id), text=admin_text)
        except TelegramAPIError:
            pass

        user_carts.pop(user_id, None)
        await state.clear()
        await _clear_bot_messages(message.bot, user_id)
        user_total = 0
        user_lines = []
        for item_id, qty in cart.items():
            meta = items.get(item_id, {})
            name = meta.get("name", item_id)
            price = int(meta.get("price") or 0)
            line_total = price * qty if price else qty
            user_total += line_total
            user_lines.append(f"- {name} x{qty} = {line_total} so'm")
        user_text = "\n".join(
            [
                f"Buyurtma #{order['order_id']} qabul qilindi.",
                *user_lines,
                f"Jami: {user_total} so'm",
            ]
        )
        sent = await message.answer(user_text, reply_markup=_main_kb())
        _remember_bot_message(user_id, sent.message_id, order_history=True)
        await _safe_delete_message(message)

    async def _submit_order(message: types.Message, state: FSMContext, user_id: int, comment: str | None) -> None:
        if user_id in submitting_orders:
            return
        submitting_orders.add(user_id)
        try:
            await _submit_order_once(message, state, user_id, comment)
        finally:
            submitting_orders.discard(user_id)

    @router.message(Checkout.comment)
    async def finish_order(message: types.Message, state: FSMContext):
        if not message.from_user:
            return
        raw_comment = (message.text or "").strip()
        if len(raw_comment) > MAX_COMMENT_LENGTH:
            await message.answer(
                f"Izoh juda uzun. Iltimos, {MAX_COMMENT_LENGTH} belgidan oshirmang.",
                reply_markup=_comment_kb(),
            )
            return
        comment = None if not raw_comment or raw_comment == "-" else raw_comment
        await _submit_order(message, state, message.from_user.id, comment)

    @router.callback_query(Checkout.comment, lambda c: c.data == "skip_comment")
    async def skip_comment(callback: CallbackQuery, state: FSMContext):
        if not callback.from_user or not callback.message:
            return await callback.answer("Foydalanuvchi aniqlanmadi", show_alert=True)
        await callback.answer()
        await _submit_order(callback.message, state, callback.from_user.id, None)

    return router
