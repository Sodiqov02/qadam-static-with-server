from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select

from finding_regression import create_tenant, isolated_app, require, run_finding


def scenario_checkout_quantity_normalization() -> None:
    with isolated_app() as (client, _):
        from src.db import get_session
        from src.db_models import Order
        from src.store import create_menu_item_for_tenant, list_categories_for_tenant

        tenant = create_tenant("quantity-a")
        other = create_tenant("quantity-b")
        category_id = list_categories_for_tenant(tenant)[0]["id"]
        other_category_id = list_categories_for_tenant(other)[0]["id"]
        item = create_menu_item_for_tenant(
            tenant,
            {"name": "Quantity dish", "price": 125, "category_id": category_id},
        )
        foreign_item = create_menu_item_for_tenant(
            other,
            {"name": "Foreign dish", "price": 999, "category_id": other_category_id},
        )
        inactive_item = create_menu_item_for_tenant(
            tenant,
            {
                "name": "Inactive dish",
                "price": 500,
                "category_id": category_id,
                "is_available": False,
            },
        )

        customer = {"name": "Quantity Test", "phone": "+998900000001", "address": "Test address"}

        def checkout(items: list[dict[str, object]]):
            return client.post("/t/quantity-a/orders", json={"items": items, "customer": customer})

        at_limit = checkout([{"item_id": str(item.id), "qty": 100}])
        require("single qty 100 succeeds", at_limit.status_code == 200, at_limit.text)

        over_limit = checkout([{"item_id": str(item.id), "qty": 101}])
        require("single qty 101 rejected", over_limit.status_code == 422, over_limit.text)

        combined_limit = checkout(
            [
                {"item_id": str(item.id), "qty": 60},
                {"item_id": str(item.id), "qty": 40},
            ]
        )
        require("duplicate qty totaling 100 succeeds", combined_limit.status_code == 200, combined_limit.text)
        with get_session() as session:
            stored = session.execute(
                select(Order).where(Order.id == combined_limit.json()["order_id"])
            ).scalar_one()
            require("duplicate rows normalized to one", len(stored.items) == 1, stored.items)
            require("normalized qty stored as 100", stored.items[0]["qty"] == 100, stored.items)
            require("normalized total charged once", stored.total == Decimal("12500"), stored.total)

        combined_over_limit = checkout(
            [
                {"item_id": str(item.id), "qty": 60},
                {"item_id": str(item.id), "qty": 41},
            ]
        )
        require(
            "duplicate qty totaling 101 rejected",
            combined_over_limit.status_code == 422,
            combined_over_limit.text,
        )

        foreign = checkout(
            [
                {"item_id": str(foreign_item.id), "qty": 60},
                {"item_id": str(foreign_item.id), "qty": 40},
            ]
        )
        require("duplicate foreign item rejected", foreign.status_code == 400, foreign.text)

        inactive = checkout([{"item_id": str(inactive_item.id), "qty": 1}])
        require("inactive item rejected", inactive.status_code == 400, inactive.text)


run_finding("checkout cumulative quantity", scenario_checkout_quantity_normalization)
