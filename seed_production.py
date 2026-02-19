from sqlalchemy.orm import Session

from src.db import engine
from src.db_models import MenuCategory, MenuItem, Tenant


def run():
    with Session(engine) as session:
        if session.query(Tenant).count() > 0:
            print("Tenants already exist. Skipping seed.")
            return

        tenants_data = [
            {
                "slug": "cafe-a",
                "name": "Cafe A",
                "admin_chat_id": 123456789,
                "bot_token": "PUT_REAL_TOKEN_1",
                "bot_username": "cafe_a_bot",
            },
            {
                "slug": "cafe-b",
                "name": "Cafe B",
                "admin_chat_id": 987654321,
                "bot_token": "PUT_REAL_TOKEN_2",
                "bot_username": "cafe_b_bot",
            },
        ]

        for data in tenants_data:
            tenant = Tenant(
                slug=data["slug"],
                name=data["name"],
                admin_chat_id=data["admin_chat_id"],
                bot_token=data["bot_token"],
                bot_username=data["bot_username"],
                bot_enabled=True,
                features={},
                is_active=True,
            )
            session.add(tenant)
            session.flush()

            category = MenuCategory(
                tenant_id=tenant.id,
                title="Основное меню",
            )
            session.add(category)
            session.flush()

            item = MenuItem(
                tenant_id=tenant.id,
                category_id=category.id,
                title="Пицца Маргарита",
                price=45000,
                is_active=True,
            )
            session.add(item)

        session.commit()
        print("Seed completed successfully.")


if __name__ == "__main__":
    run()
