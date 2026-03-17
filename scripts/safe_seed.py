import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import select

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from src.db import get_session
from src.db_models import MenuCategory, MenuItem, Tenant
from src.store import bootstrap_tenant

DEFAULT_CATEGORIES = (
    ("Main", 0),
    ("Drinks", 1),
    ("Desserts", 2),
)

DEFAULT_ITEMS = (
    {"category": "Main", "title": "Osh", "price": 35000, "description": "Traditional Uzbek pilaf", "sort": 0},
    {"category": "Main", "title": "Lagman", "price": 32000, "description": "Hand-pulled noodle soup", "sort": 1},
    {"category": "Drinks", "title": "Tea", "price": 5000, "description": "Hot black tea", "sort": 0},
    {"category": "Desserts", "title": "Honey cake", "price": 18000, "description": "Soft layered cake", "sort": 0},
)


def safe_seed_tenant(
    *,
    slug: str,
    name: str,
    admin_chat_id: int,
    plan: str = "standard",
) -> dict:
    result = bootstrap_tenant(
        slug=slug,
        name=name,
        admin_chat_id=admin_chat_id,
        bot_token=None,
        bot_username=None,
        bot_enabled=False,
        features={"plan": plan, "reservations": True},
        category_titles=[title for title, _ in DEFAULT_CATEGORIES],
    )

    with get_session() as session:
        tenant = session.execute(select(Tenant).where(Tenant.slug == slug)).scalar_one()
        categories = (
            session.execute(
                select(MenuCategory)
                .where(MenuCategory.tenant_id == tenant.id)
                .order_by(MenuCategory.sort_order, MenuCategory.sort, MenuCategory.id)
            )
            .scalars()
            .all()
        )
        categories_by_title = {category.title: category for category in categories}

        for title, sort_order in DEFAULT_CATEGORIES:
            category = categories_by_title.get(title)
            if not category:
                category = MenuCategory(
                    tenant_id=tenant.id,
                    title=title,
                    sort=sort_order,
                    sort_order=sort_order,
                )
                session.add(category)
                session.flush()
                categories_by_title[title] = category
                result["categories_created"] = int(result.get("categories_created", 0)) + 1
            elif getattr(category, "sort_order", None) is None:
                category.sort_order = sort_order

        existing_items = {
            (item.category_id, item.title): item
            for item in session.execute(select(MenuItem).where(MenuItem.tenant_id == tenant.id)).scalars().all()
        }

        items_created = 0
        for row in DEFAULT_ITEMS:
            category = categories_by_title.get(row["category"])
            if not category:
                continue
            key = (category.id, row["title"])
            if key in existing_items:
                continue
            session.add(
                MenuItem(
                    tenant_id=tenant.id,
                    category_id=category.id,
                    title=row["title"],
                    price=int(row["price"]),
                    description=row["description"],
                    is_active=True,
                    sort=int(row["sort"]),
                )
            )
            items_created += 1

    result["items_created"] = items_created
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Safely seed one demo tenant without deleting existing data")
    parser.add_argument("--slug", default="cafe-a", help="Tenant slug")
    parser.add_argument("--name", default="Cafe A", help="Tenant display name")
    parser.add_argument("--admin-chat-id", type=int, default=100000001, help="Admin Telegram chat id")
    parser.add_argument("--plan", default="standard", help="Plan: basic | standard | vip")
    args = parser.parse_args()

    result = safe_seed_tenant(
        slug=args.slug.strip(),
        name=args.name.strip(),
        admin_chat_id=int(args.admin_chat_id),
        plan=(args.plan or "standard").strip().lower(),
    )
    print(json.dumps({"status": "ok", **result}, ensure_ascii=True))


if __name__ == "__main__":
    main()
