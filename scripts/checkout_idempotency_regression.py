from __future__ import annotations

import concurrent.futures
import threading

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from finding_regression import create_tenant, isolated_app, require, run_finding


def scenario_checkout_idempotency() -> None:
    with isolated_app() as (client, app):
        import src.api_app as api_app
        from src.db import get_session
        from src.db_models import Order
        from src.store import create_menu_item_for_tenant, list_categories_for_tenant

        tenant_a = create_tenant("idempotency-a")
        tenant_b = create_tenant("idempotency-b")
        category_a = list_categories_for_tenant(tenant_a)[0]["id"]
        category_b = list_categories_for_tenant(tenant_b)[0]["id"]
        item_a = create_menu_item_for_tenant(
            tenant_a,
            {"name": "A dish", "price": 125, "category_id": category_a},
        )
        item_a_second = create_menu_item_for_tenant(
            tenant_a,
            {"name": "A second dish", "price": 250, "category_id": category_a},
        )
        item_b = create_menu_item_for_tenant(
            tenant_b,
            {"name": "B dish", "price": 500, "category_id": category_b},
        )

        customer = {"name": "Idempotency Test", "phone": "+998900000001", "address": "Test address"}
        payload_a = {"items": [{"item_id": str(item_a.id), "qty": 1}], "customer": customer}
        notifications: list[tuple[int, int]] = []
        notification_lock = threading.Lock()
        original_notify_admin = api_app.notify_admin

        async def record_notification(order_id: int, tenant_id: int) -> None:
            with notification_lock:
                notifications.append((order_id, tenant_id))

        api_app.notify_admin = record_notification
        try:
            first = client.post(
                "/t/idempotency-a/orders",
                headers={"Idempotency-Key": "sequential-key"},
                json=payload_a,
            )
            require("first keyed checkout succeeds", first.status_code == 200, first.text)
            first_id = first.json()["order_id"]
            require("first checkout notifies once", len(notifications) == 1, notifications)

            replay = client.post(
                "/t/idempotency-a/orders",
                headers={"Idempotency-Key": "sequential-key"},
                json=payload_a,
            )
            require("sequential replay succeeds", replay.status_code == 200, replay.text)
            require("sequential replay returns original order", replay.json()["order_id"] == first_id, replay.text)
            require("sequential replay does not notify again", len(notifications) == 1, notifications)

            conflict_payload = {**payload_a, "items": [{"item_id": str(item_a.id), "qty": 2}]}
            conflict = client.post(
                "/t/idempotency-a/orders",
                headers={"Idempotency-Key": "sequential-key"},
                json=conflict_payload,
            )
            require("same key with different payload conflicts", conflict.status_code == 409, conflict.text)

            different_key = client.post(
                "/t/idempotency-a/orders",
                headers={"Idempotency-Key": "different-key"},
                json=payload_a,
            )
            require("different key succeeds", different_key.status_code == 200, different_key.text)
            require("different key creates a new order", different_key.json()["order_id"] != first_id, different_key.text)

            tenant_b_response = client.post(
                "/t/idempotency-b/orders",
                headers={"Idempotency-Key": "sequential-key"},
                json={"items": [{"item_id": str(item_b.id), "qty": 1}], "customer": customer},
            )
            require("same key is independent across tenants", tenant_b_response.status_code == 200, tenant_b_response.text)

            without_key = client.post("/t/idempotency-a/orders", json=payload_a)
            require("checkout without key remains compatible", without_key.status_code == 200, without_key.text)

            equivalent_payload = {
                "items": [
                    {"item_id": str(item_a.id), "qty": 1},
                    {"item_id": str(item_a_second.id), "qty": 2},
                ],
                "customer": customer,
            }
            equivalent_first = client.post(
                "/t/idempotency-a/orders",
                headers={"Idempotency-Key": "equivalent-order-key"},
                json=equivalent_payload,
            )
            equivalent_replay = client.post(
                "/t/idempotency-a/orders",
                headers={"Idempotency-Key": "equivalent-order-key"},
                json={**equivalent_payload, "items": list(reversed(equivalent_payload["items"]))},
            )
            require("equivalent item ordering succeeds", equivalent_replay.status_code == 200, equivalent_replay.text)
            require(
                "equivalent item ordering returns original order",
                equivalent_replay.json()["order_id"] == equivalent_first.json()["order_id"],
                equivalent_replay.text,
            )

            concurrent_key = "concurrent-key"
            with TestClient(app) as second_client:
                def submit(test_client: TestClient):
                    return test_client.post(
                        "/t/idempotency-a/orders",
                        headers={"Idempotency-Key": concurrent_key},
                        json=payload_a,
                    )

                with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                    responses = list(executor.map(submit, (client, second_client)))

            require("concurrent requests succeed", all(response.status_code == 200 for response in responses), responses)
            concurrent_ids = {response.json()["order_id"] for response in responses}
            require("concurrent requests return one order", len(concurrent_ids) == 1, concurrent_ids)

            with get_session() as session:
                sequential_count = session.execute(
                    select(func.count(Order.id)).where(
                        Order.tenant_id == tenant_a.id,
                        Order.idempotency_key == "sequential-key",
                    )
                ).scalar_one()
                concurrent_count = session.execute(
                    select(func.count(Order.id)).where(
                        Order.tenant_id == tenant_a.id,
                        Order.idempotency_key == concurrent_key,
                    )
                ).scalar_one()
            require("sequential replay leaves one order", sequential_count == 1, sequential_count)
            require("concurrent replay leaves one order", concurrent_count == 1, concurrent_count)

            concurrent_id = next(iter(concurrent_ids))
            concurrent_notifications = [row for row in notifications if row[0] == concurrent_id]
            require("concurrent replay notifies once", len(concurrent_notifications) == 1, concurrent_notifications)
        finally:
            api_app.notify_admin = original_notify_admin


run_finding("checkout idempotency", scenario_checkout_idempotency)
