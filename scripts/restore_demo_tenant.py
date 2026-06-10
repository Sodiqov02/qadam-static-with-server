from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import select

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))


DEMO_CATEGORIES = (
    ("Burgerlar", 0),
    ("Lavash", 1),
    ("Pizza", 2),
    ("Salatlar", 3),
    ("Snacklar", 4),
    ("Ichimliklar", 5),
)

DEMO_ITEMS = (
    {
        "title": "Classic Burger",
        "category": "Burgerlar",
        "price": 39000,
        "description": "Mol go'shti kotleti, cheddar pishlog'i, yangi sabzavot va maxsus sous.",
        "image_url": "/static/demo/menu/classic-burger.webp",
        "sort": 0,
    },
    {
        "title": "Cheese Burger",
        "category": "Burgerlar",
        "price": 43000,
        "description": "Ikki qavat cheddar, yumshoq bulochka, tuzlangan bodring va burger sousi.",
        "image_url": "/static/demo/menu/cheese-burger.webp",
        "sort": 1,
    },
    {
        "title": "Chicken Lavash",
        "category": "Lavash",
        "price": 33000,
        "description": "Tovuq filesi, sabzavotlar, fri kartoshka va oq sous bilan o'ralgan lavash.",
        "image_url": "/static/demo/menu/chicken-lavash.webp",
        "sort": 0,
    },
    {
        "title": "Beef Lavash",
        "category": "Lavash",
        "price": 37000,
        "description": "Mol go'shti, yangi ko'katlar, pomidor va achchiq sousli katta lavash.",
        "image_url": "/static/demo/menu/beef-lavash.webp",
        "sort": 1,
    },
    {
        "title": "Pepperoni Pizza",
        "category": "Pizza",
        "price": 69000,
        "description": "Mozzarella, pepperoni kolbasasi va pomidor sousli issiq pizza.",
        "image_url": "/static/demo/menu/pepperoni-pizza.webp",
        "sort": 0,
    },
    {
        "title": "Margherita Pizza",
        "category": "Pizza",
        "price": 59000,
        "description": "Mozzarella, pomidor, rayhon va zaytun moyi bilan klassik pizza.",
        "image_url": "/static/demo/menu/margherita-pizza.webp",
        "sort": 1,
    },
    {
        "title": "Caesar Salad",
        "category": "Salatlar",
        "price": 35000,
        "description": "Tovuq filesi, romaine salati, parmesan, kruton va caesar sousi.",
        "image_url": "/static/demo/menu/caesar-salad.webp",
        "sort": 0,
    },
    {
        "title": "Fri Kartoshka",
        "category": "Snacklar",
        "price": 18000,
        "description": "Qarsildoq fri kartoshka, ketchup va maxsus ziravorlar bilan.",
        "image_url": "/static/demo/menu/fries.webp",
        "sort": 0,
    },
    {
        "title": "Firma kolasi",
        "category": "Ichimliklar",
        "price": 10000,
        "description": "Sovutilgan firma kola ichimligi.",
        "image_url": "/static/demo/menu/signature-cola.webp",
        "sort": 0,
    },
)


PRODUCTION_ENV_VALUES = {"production", "prod", "staging"}
CLI_ADMIN_SECRET_PLACEHOLDER = "restore_demo_tenant_cli_override_secret"


def _db_deps():
    from src.db import get_session
    from src.db_models import MenuCategory, MenuItem, Tenant

    return get_session, MenuCategory, MenuItem, Tenant


def _is_production_like() -> bool:
    if os.getenv("RAILWAY_ENVIRONMENT"):
        return True
    for key in ("APP_ENV", "ENVIRONMENT", "QADAM_ENV", "ENV"):
        if (os.getenv(key) or "").strip().lower() in PRODUCTION_ENV_VALUES:
            return True
    return False


def _planned_value_change(current: Any, desired: Any) -> dict | None:
    if current == desired:
        return None
    return {"from": current, "to": desired}


def _tenant_plan(tenant: Tenant | None, slug: str) -> dict:
    current_features = dict(getattr(tenant, "features", None) or {})
    desired_features = dict(current_features)
    desired_features.update(
        {
            "plan": "standard",
            "reservations": True,
            "description": (
                "Restoranlar uchun to'g'ridan-to'g'ri buyurtmalar, ko'p tilli mehmonlar "
                "va qulay checkout uchun yaratilgan nafis online buyurtma tajribasi."
            ),
            "hero_image": "/static/demo/menu/classic-burger.webp",
        }
    )
    if tenant is None:
        return {
            "action": "create",
            "slug": slug,
            "name": "Qadam Demo",
            "theme_mode": "default",
            "features": desired_features,
        }

    branding_changes = {}
    for field, desired in (
        ("name", "Qadam Demo"),
        ("logo_url", None),
        ("primary_color", None),
        ("accent_color", None),
        ("theme_mode", "default"),
    ):
        change = _planned_value_change(getattr(tenant, field), desired)
        if change:
            branding_changes[field] = change

    features_change = _planned_value_change(current_features, desired_features)
    if features_change:
        branding_changes["features"] = features_change

    return {
        "action": "update" if branding_changes else "unchanged",
        "slug": tenant.slug,
        "branding_changes": branding_changes,
    }


def _build_plan(slug: str) -> dict:
    get_session, MenuCategory, MenuItem, Tenant = _db_deps()
    desired_categories = {title for title, _ in DEMO_CATEGORIES}
    desired_items = {row["title"] for row in DEMO_ITEMS}

    with get_session() as session:
        tenant = session.execute(select(Tenant).where(Tenant.slug == slug)).scalar_one_or_none()
        plan = {
            "slug": slug,
            "tenant": _tenant_plan(tenant, slug),
            "branding": None,
            "categories": {"create": [], "update": [], "delete": []},
            "items": {"create": [], "update": [], "delete": []},
        }
        plan["branding"] = plan["tenant"]

        if tenant is None:
            plan["categories"]["create"] = [
                {"title": title, "sort": sort_order, "sort_order": sort_order}
                for title, sort_order in DEMO_CATEGORIES
            ]
            plan["items"]["create"] = [dict(row) for row in DEMO_ITEMS]
            return plan

        existing_categories = {
            category.title: category
            for category in session.execute(
                select(MenuCategory).where(MenuCategory.tenant_id == tenant.id)
            ).scalars()
        }
        for title, sort_order in DEMO_CATEGORIES:
            category = existing_categories.get(title)
            if category is None:
                plan["categories"]["create"].append({"title": title, "sort": sort_order, "sort_order": sort_order})
                continue
            changes = {}
            for field, desired in (("sort", sort_order), ("sort_order", sort_order)):
                change = _planned_value_change(getattr(category, field), desired)
                if change:
                    changes[field] = change
            if changes:
                plan["categories"]["update"].append({"title": title, "changes": changes})

        for category in existing_categories.values():
            if category.title not in desired_categories:
                plan["categories"]["delete"].append({"id": category.id, "title": category.title})

        existing_items = {
            item.title: item
            for item in session.execute(select(MenuItem).where(MenuItem.tenant_id == tenant.id)).scalars()
        }
        for item in existing_items.values():
            if item.title not in desired_items:
                plan["items"]["delete"].append({"id": item.id, "title": item.title})

        categories_by_title = existing_categories
        for row in DEMO_ITEMS:
            item = existing_items.get(row["title"])
            if item is None:
                plan["items"]["create"].append(dict(row))
                continue
            category = categories_by_title.get(row["category"])
            desired_category_id = category.id if category else f"category:{row['category']}"
            changes = {}
            desired_values = {
                "category_id": desired_category_id,
                "price": int(row["price"]),
                "description": row["description"],
                "image_path": None,
                "image_url": row["image_url"],
                "is_active": True,
                "sort": int(row["sort"]),
            }
            for field, desired in desired_values.items():
                change = _planned_value_change(getattr(item, field), desired)
                if change:
                    changes[field] = change
            if changes:
                plan["items"]["update"].append({"title": row["title"], "changes": changes})

        return plan


def restore_demo_tenant(slug: str = "demo", *, dry_run: bool = False) -> dict:
    get_session, MenuCategory, MenuItem, Tenant = _db_deps()
    plan = _build_plan(slug)
    if dry_run:
        return {"dry_run": True, "plan": plan}

    desired_categories = {title for title, _ in DEMO_CATEGORIES}
    desired_items = {row["title"] for row in DEMO_ITEMS}

    with get_session() as session:
        tenant = session.execute(select(Tenant).where(Tenant.slug == slug)).scalar_one_or_none()
        if tenant is None:
            tenant = Tenant(
                slug=slug,
                name="Qadam Demo",
                admin_chat_id=100000001,
                features={"plan": "standard", "reservations": True},
                is_active=True,
                theme_mode="default",
            )
            session.add(tenant)
            session.flush()

        tenant.name = "Qadam Demo"
        tenant.logo_url = None
        tenant.primary_color = None
        tenant.accent_color = None
        tenant.theme_mode = "default"
        features = dict(tenant.features or {})
        features.update(
            {
                "plan": "standard",
                "reservations": True,
                "description": (
                    "Restoranlar uchun to'g'ridan-to'g'ri buyurtmalar, ko'p tilli mehmonlar "
                    "va qulay checkout uchun yaratilgan nafis online buyurtma tajribasi."
                ),
                "hero_image": "/static/demo/menu/classic-burger.webp",
            }
        )
        tenant.features = features
        tenant.is_active = True
        session.flush()

        existing_categories = {
            category.title: category
            for category in session.execute(
                select(MenuCategory).where(MenuCategory.tenant_id == tenant.id)
            ).scalars()
        }
        categories_created = 0
        for title, sort_order in DEMO_CATEGORIES:
            category = existing_categories.get(title)
            if category is None:
                category = MenuCategory(
                    tenant_id=tenant.id,
                    title=title,
                    sort=sort_order,
                    sort_order=sort_order,
                )
                session.add(category)
                session.flush()
                existing_categories[title] = category
                categories_created += 1
            else:
                category.sort = sort_order
                category.sort_order = sort_order

        items = session.execute(select(MenuItem).where(MenuItem.tenant_id == tenant.id)).scalars().all()
        for item in items:
            if item.title not in desired_items:
                session.delete(item)
        session.flush()

        for category in list(existing_categories.values()):
            if category.title not in desired_categories:
                session.delete(category)
        session.flush()

        categories_by_title = {
            category.title: category
            for category in session.execute(
                select(MenuCategory).where(MenuCategory.tenant_id == tenant.id)
            ).scalars()
        }
        items_by_title = {
            item.title: item
            for item in session.execute(select(MenuItem).where(MenuItem.tenant_id == tenant.id)).scalars()
        }

        items_created = 0
        for row in DEMO_ITEMS:
            category = categories_by_title[row["category"]]
            item = items_by_title.get(row["title"])
            if item is None:
                item = MenuItem(tenant_id=tenant.id, title=row["title"])
                session.add(item)
                items_created += 1
            item.category_id = category.id
            item.price = int(row["price"])
            item.description = row["description"]
            item.image_path = None
            item.image_url = row["image_url"]
            item.is_active = True
            item.sort = int(row["sort"])

        return {
            "dry_run": False,
            "tenant_id": tenant.id,
            "slug": tenant.slug,
            "categories": len(DEMO_CATEGORIES),
            "items": len(DEMO_ITEMS),
            "categories_created": categories_created,
            "items_created": items_created,
            "plan": plan,
        }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Destructive demo-only tool: resets one tenant's branding, categories, and menu "
            "to the premium Qadam demo data."
        )
    )
    parser.add_argument("--slug", default="demo", help="Tenant slug to restore")
    parser.add_argument("--dry-run", action="store_true", help="Print planned changes without writing to the database")
    parser.add_argument("--force", action="store_true", help="Allow restoring a non-demo slug in non-production env")
    parser.add_argument(
        "--i-understand-this-can-delete-tenant-data",
        action="store_true",
        help="Required to bypass production/staging safety guard",
    )
    args = parser.parse_args()
    slug = args.slug.strip()
    if slug != "demo" and not args.force:
        raise SystemExit("Refusing to restore a non-demo slug without --force.")
    if _is_production_like() and not args.i_understand_this_can_delete_tenant_data:
        raise SystemExit(
            "Refusing to run in production/staging environment without "
            "--i-understand-this-can-delete-tenant-data."
        )
    if _is_production_like() and args.i_understand_this_can_delete_tenant_data:
        os.environ.setdefault("ADMIN_SECRET", CLI_ADMIN_SECRET_PLACEHOLDER)
    result = restore_demo_tenant(slug=slug, dry_run=bool(args.dry_run))
    print(json.dumps({"status": "ok", **result}, ensure_ascii=True))


if __name__ == "__main__":
    main()
