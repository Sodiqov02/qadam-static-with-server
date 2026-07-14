from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any


BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ADMIN_SECRET", "telegram_checkout_regression_secret")
os.environ.setdefault("API_BASE_URL", "http://testserver")


class FakeState:
    def __init__(self) -> None:
        self.data: dict[str, Any] = {}
        self.current_state = None

    async def update_data(self, **kwargs) -> None:
        self.data.update(kwargs)

    async def get_data(self) -> dict[str, Any]:
        await asyncio.sleep(0)
        return dict(self.data)

    async def set_state(self, state) -> None:
        self.current_state = state

    async def clear(self) -> None:
        self.data.clear()
        self.current_state = None


class FakeBot:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.deleted: list[tuple[int, int]] = []

    async def send_message(self, chat_id: int, text: str, reply_markup=None):
        self.sent.append({"chat_id": chat_id, "text": text, "reply_markup": reply_markup})
        return SimpleNamespace(message_id=1000 + len(self.sent))

    async def delete_message(self, chat_id: int, message_id: int) -> None:
        self.deleted.append((chat_id, message_id))


class FakeMessage:
    _next_id = 100

    def __init__(self, bot: FakeBot, user_id: int, text: str | None = None, *, reject_edits: bool = False) -> None:
        self.bot = bot
        self.from_user = SimpleNamespace(id=user_id)
        self.text = text
        self.reject_edits = reject_edits
        self.answers: list[dict[str, Any]] = []
        self.edits: list[dict[str, Any]] = []
        self.deleted = False

    async def answer(self, text: str, reply_markup=None):
        self.answers.append({"text": text, "reply_markup": reply_markup})
        FakeMessage._next_id += 1
        return SimpleNamespace(message_id=FakeMessage._next_id)

    async def edit_text(self, text: str, reply_markup=None):
        if self.reject_edits:
            raise AssertionError("checkout attempted edit_text and could trigger message is not modified")
        self.edits.append({"text": text, "reply_markup": reply_markup})

    async def delete(self) -> None:
        self.deleted = True


class FakeCallback:
    def __init__(self, user_id: int, data: str, message: FakeMessage) -> None:
        self.from_user = SimpleNamespace(id=user_id)
        self.data = data
        self.message = message
        self.answers: list[dict[str, Any]] = []

    async def answer(self, text: str | None = None, show_alert: bool = False) -> None:
        self.answers.append({"text": text, "show_alert": show_alert})


class FakeResponse:
    def __init__(self, order_id: int) -> None:
        self._order_id = order_id

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, int]:
        return {"order_id": self._order_id}


class FakeAsyncClient:
    payloads: list[dict[str, Any]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None

    async def post(self, url: str, *, json: dict[str, Any], headers: dict[str, str], timeout: int):
        await asyncio.sleep(0.02)
        self.payloads.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return FakeResponse(len(self.payloads))


def _handler(router, observer: str, name: str):
    handlers = getattr(router, observer).handlers
    return next(item.callback for item in handlers if item.callback.__name__ == name)


async def _prepare_flow(user_module, *, user_id: int):
    tenant = SimpleNamespace(slug="demo", admin_chat_id=9001)
    router = user_module.create_user_router(tenant)
    callbacks = {name: _handler(router, "callback_query", name) for name in ("add_to_cart", "checkout_callback")}
    messages = {
        name: _handler(router, "message", name)
        for name in ("get_name", "get_phone", "get_address", "finish_order")
    }
    bot = FakeBot()
    state = FakeState()

    add_message = FakeMessage(bot, user_id)
    await callbacks["add_to_cart"](FakeCallback(user_id, "add:1", add_message))
    checkout_message = FakeMessage(bot, user_id, reject_edits=True)
    await callbacks["checkout_callback"](FakeCallback(user_id, "checkout", checkout_message), state)
    assert state.current_state is not None and "Checkout:name" in str(state.current_state)

    await messages["get_name"](FakeMessage(bot, user_id, "Ali"), state)
    await messages["get_phone"](FakeMessage(bot, user_id, "+998901234567"), state)
    address_message = FakeMessage(bot, user_id, "Toshkent, 1-uy")
    await messages["get_address"](address_message, state)
    prompt = address_message.answers[-1]
    assert "Buyurtmaga izoh" in prompt["text"]
    button = prompt["reply_markup"].inline_keyboard[0][0]
    assert button.text == "O'tkazib yuborish" and button.callback_data == "skip_comment"
    return router, messages, bot, state


async def main_async() -> list[str]:
    import src.handlers.user as user_module

    issues: list[str] = []
    original_client = user_module.httpx.AsyncClient
    original_item_map = user_module.get_menu_item_map_for_tenant
    user_module.httpx.AsyncClient = FakeAsyncClient
    user_module.get_menu_item_map_for_tenant = lambda tenant, keys: {
        str(key): {"id": str(key), "name": "Osh", "price": 35000} for key in keys
    }

    def expect(label: str, condition: bool, detail: str = "") -> None:
        if not condition:
            issues.append(f"{label}: {detail}".rstrip())

    try:
        FakeAsyncClient.payloads.clear()
        router, messages, bot, state = await _prepare_flow(user_module, user_id=101)
        await messages["finish_order"](FakeMessage(bot, 101, "Piyozsiz"), state)
        expect("text comment order created", len(FakeAsyncClient.payloads) == 1)
        expect("text comment stored", FakeAsyncClient.payloads[-1]["json"]["customer"]["comment"] == "Piyozsiz")
        expect("text comment admin notified once", sum("Yangi buyurtma" in row["text"] for row in bot.sent) == 1)

        FakeAsyncClient.payloads.clear()
        router, _, bot, state = await _prepare_flow(user_module, user_id=102)
        skip = _handler(router, "callback_query", "skip_comment")
        skip_message = FakeMessage(bot, 102)
        first = FakeCallback(102, "skip_comment", skip_message)
        second = FakeCallback(102, "skip_comment", skip_message)
        await asyncio.gather(skip(first, state), skip(second, state))
        expect("skip callbacks answered", len(first.answers) == 1 and len(second.answers) == 1)
        expect("double skip creates one order", len(FakeAsyncClient.payloads) == 1, str(len(FakeAsyncClient.payloads)))
        expect("skip stores null comment", FakeAsyncClient.payloads[-1]["json"]["customer"]["comment"] is None)
        expect("skip admin notified once", sum("Yangi buyurtma" in row["text"] for row in bot.sent) == 1)

        FakeAsyncClient.payloads.clear()
        _, messages, bot, state = await _prepare_flow(user_module, user_id=103)
        await messages["finish_order"](FakeMessage(bot, 103, "-"), state)
        expect("dash stores null comment", FakeAsyncClient.payloads[-1]["json"]["customer"]["comment"] is None)

        FakeAsyncClient.payloads.clear()
        tenant = SimpleNamespace(slug="demo", admin_chat_id=9001)
        empty_router = user_module.create_user_router(tenant)
        empty_checkout = _handler(empty_router, "callback_query", "checkout_callback")
        empty_state = FakeState()
        empty_message = FakeMessage(FakeBot(), 104)
        await empty_checkout(FakeCallback(104, "checkout", empty_message), empty_state)
        expect("empty cart does not start checkout", empty_state.current_state is None)
        expect("empty cart does not create order", not FakeAsyncClient.payloads)
        expect("empty cart shows message", bool(empty_message.edits))

        _, messages, bot, state = await _prepare_flow(user_module, user_id=105)
        long_message = FakeMessage(bot, 105, "x" * 2001)
        await messages["finish_order"](long_message, state)
        expect("long comment rejected before API", not FakeAsyncClient.payloads)
        expect("long comment keeps checkout state", state.current_state is not None)
        expect("long comment has clear error", "2000" in long_message.answers[-1]["text"])
    except Exception as exc:
        issues.append(f"unexpected exception: {type(exc).__name__}: {exc}")
    finally:
        user_module.httpx.AsyncClient = original_client
        user_module.get_menu_item_map_for_tenant = original_item_map

    return issues


def main() -> None:
    issues = asyncio.run(main_async())
    print(json.dumps({"status": "ok" if not issues else "failed", "issues": issues}, indent=2))
    if issues:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
