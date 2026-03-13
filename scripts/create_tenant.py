import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramAPIError, TelegramUnauthorizedError
from aiogram.utils.token import TokenValidationError
from sqlalchemy import select

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from src.db import get_session
from src.db_models import MenuCategory, MenuItem, Tenant
from src.store import bootstrap_tenant, get_tenant_by_slug

logger = logging.getLogger(__name__)

DEFAULT_CATEGORIES = ("Main", "Drinks", "Desserts")
DEFAULT_MENU_ITEMS = (
    {"category": "Main", "title": "Osh", "price": 35000, "description": "Traditional Uzbek pilaf"},
    {"category": "Main", "title": "Lagman", "price": 32000, "description": "Hand-pulled noodle soup"},
    {"category": "Drinks", "title": "Tea", "price": 5000, "description": "Hot black tea"},
)


def _normalize_plan(plan: str) -> str:
    value = (plan or "").strip().lower()
    if value not in {"basic", "standard", "vip"}:
        raise ValueError("Plan must be one of: basic, standard, vip")
    return value


def _build_public_base_url() -> str:
    base_url = (os.getenv("API_BASE_URL") or "").strip().rstrip("/")
    if base_url.endswith("/api"):
        base_url = base_url[:-4]
    if base_url:
        parsed = urlparse(base_url)
        if parsed.scheme and parsed.netloc:
            return base_url
    return "https://YOUR_DOMAIN"


async def _validate_bot_token(bot_token: str) -> str:
    bot = Bot(token=bot_token, default=DefaultBotProperties(parse_mode=None))
    try:
        me = await bot.get_me()
        return me.username or ""
    finally:
        await bot.session.close()


def _create_demo_menu(tenant_slug: str) -> None:
    with get_session() as session:
        tenant = session.execute(select(Tenant).where(Tenant.slug == tenant_slug)).scalar_one()
        categories = (
            session.execute(select(MenuCategory).where(MenuCategory.tenant_id == tenant.id))
            .scalars()
            .all()
        )
        by_title = {c.title: c for c in categories}
        next_sort = (
            session.execute(
                select(MenuItem.sort)
                .where(MenuItem.tenant_id == tenant.id)
                .order_by(MenuItem.sort.desc(), MenuItem.id.desc())
                .limit(1)
            ).scalar_one_or_none()
            or -1
        )

        for row in DEFAULT_MENU_ITEMS:
            category = by_title.get(row["category"])
            if not category:
                continue
            exists = session.execute(
                select(MenuItem).where(
                    MenuItem.tenant_id == tenant.id,
                    MenuItem.category_id == category.id,
                    MenuItem.title == row["title"],
                )
            ).scalar_one_or_none()
            if exists:
                continue
            next_sort += 1
            session.add(
                MenuItem(
                    tenant_id=tenant.id,
                    category_id=category.id,
                    title=row["title"],
                    price=int(row["price"]),
                    description=row["description"],
                    is_active=True,
                    sort=next_sort,
                )
            )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

    parser = argparse.ArgumentParser(description="Create a new restaurant tenant with demo data")
    parser.add_argument("--slug", required=True, help="Tenant slug (unique)")
    parser.add_argument("--name", required=True, help="Restaurant name")
    parser.add_argument("--bot-token", help="Telegram bot token")
    parser.add_argument("--admin-chat-id", required=True, type=int, help="Admin Telegram chat id")
    parser.add_argument("--plan", required=True, help="Plan: basic | standard | vip")
    args = parser.parse_args()

    slug = args.slug.strip()
    name = args.name.strip()
    plan = _normalize_plan(args.plan)

    if get_tenant_by_slug(slug):
        print("Tenant with slug already exists")
        raise SystemExit(1)

    bot_token = (args.bot_token or "").strip() or None
    bot_username = None
    bot_enabled = False

    if bot_token:
        try:
            bot_username = asyncio.run(_validate_bot_token(bot_token))
            bot_enabled = True
        except (TokenValidationError, TelegramUnauthorizedError):
            print("Invalid Telegram bot token")
            raise SystemExit(1)
        except TelegramAPIError as exc:
            logger.exception("telegram_token_validation_failed slug=%s", slug)
            raise SystemExit(str(exc))

    bootstrap_tenant(
        slug=slug,
        name=name,
        admin_chat_id=args.admin_chat_id,
        bot_token=bot_token,
        bot_username=bot_username,
        bot_enabled=bot_enabled,
        features={"plan": plan, "reservations": True},
        category_titles=DEFAULT_CATEGORIES,
    )
    _create_demo_menu(slug)

    public_base_url = _build_public_base_url()
    telegram_url = f"https://t.me/{bot_username}" if bot_username else "https://t.me/<bot_username>"

    logger.info("tenant_created slug=%s", slug)
    print("Tenant created successfully\n")
    print(f"Restaurant: {name}")
    print(f"Slug: {slug}\n")
    print("Menu:")
    print(f"{public_base_url}/t/{slug}/menu\n")
    print("Admin panel:")
    print(f"{public_base_url}/t/{slug}/admin\n")
    print("Telegram bot:")
    print(telegram_url)


if __name__ == "__main__":
    main()
