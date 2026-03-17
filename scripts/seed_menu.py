import argparse
import sys
from pathlib import Path

from sqlalchemy import select

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))


CATEGORIES_DATA = (
    ("Burgers", 0),
    ("Snacks", 1),
    ("Drinks", 2),
)

ITEMS_DATA = (
    ("Classic Burger", "Burgers", 45000, 0),
    ("Double Burger", "Burgers", 55000, 1),
    ("Chicken Burger", "Burgers", 48000, 2),
    ("French Fries", "Snacks", 20000, 0),
    ("Nuggets", "Snacks", 25000, 1),
    ("Onion Rings", "Snacks", 22000, 2),
    ("Cola", "Drinks", 12000, 0),
    ("Fanta", "Drinks", 12000, 1),
    ("Water", "Drinks", 8000, 2),
)


def seed_menu(slug: str) -> dict:
    from src.db import get_session
    from src.db_models import MenuCategory, MenuItem, Tenant

    with get_session() as session:
        tenant = session.execute(select(Tenant).where(Tenant.slug == slug)).scalar_one_or_none()
        if not tenant:
            raise ValueError(f"Tenant with slug '{slug}' not found")

        categories = (
            session.execute(select(MenuCategory).where(MenuCategory.tenant_id == tenant.id))
            .scalars()
            .all()
        )
        categories_by_title = {c.title: c for c in categories}
        categories_created = 0

        for title, sort in CATEGORIES_DATA:
            if title in categories_by_title:
                continue
            category = MenuCategory(tenant_id=tenant.id, title=title, sort=sort, sort_order=sort)
            session.add(category)
            session.flush()
            categories_by_title[title] = category
            categories_created += 1

        existing_items = {
            (item.category_id, item.title)
            for item in (
                session.execute(select(MenuItem).where(MenuItem.tenant_id == tenant.id))
                .scalars()
                .all()
            )
        }
        items_created = 0

        for title, category_title, price, sort in ITEMS_DATA:
            category = categories_by_title.get(category_title)
            if not category:
                continue
            key = (category.id, title)
            if key in existing_items:
                continue
            session.add(
                MenuItem(
                    tenant_id=tenant.id,
                    category_id=category.id,
                    title=title,
                    price=price,
                    is_active=True,
                    sort=sort,
                )
            )
            existing_items.add(key)
            items_created += 1

        return {
            "tenant_id": tenant.id,
            "slug": tenant.slug,
            "categories_created": categories_created,
            "items_created": items_created,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed demo menu for tenant by slug")
    parser.add_argument("slug", help="Tenant slug")
    args = parser.parse_args()

    result = seed_menu(args.slug.strip())
    print(
        "Menu seed completed: "
        f"slug={result['slug']} "
        f"categories_created={result['categories_created']} "
        f"items_created={result['items_created']}"
    )


if __name__ == "__main__":
    main()
