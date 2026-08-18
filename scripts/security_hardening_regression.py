from __future__ import annotations

import concurrent.futures
import base64
import hashlib
import json
import os
import sys
import tempfile
import time
from datetime import datetime, time as dt_time, timedelta, timezone
from pathlib import Path

from fastapi import BackgroundTasks, Request
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import SQLAlchemyError


BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))


def main() -> None:
    issues: list[str] = []

    def expect(label: str, condition: bool, detail: str = "") -> None:
        if not condition:
            issues.append(f"{label}: {detail}".rstrip())

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        tmp_path = Path(tmp)
        os.environ["DATABASE_URL"] = f"sqlite:///{(tmp_path / 'security.db').as_posix()}"
        os.environ["ADMIN_SECRET"] = "security_regression_secret"
        os.environ["API_BASE_URL"] = "http://testserver"
        os.environ["UPLOADS_DIR"] = str(tmp_path / "uploads")
        os.environ["MENU_IMAGES_DIR"] = str(tmp_path / "menu_images")

        import src.api_app as api_app
        from src.api_app import InMemoryRateLimiter, app, create_order_by_slug, rate_limiter
        from src.db import engine, get_session
        from src.db_models import (
            AdminLoginToken,
            AdminSession,
            MenuCategory,
            MenuItem,
            OperatorSession,
            Order,
            Reservation,
            Table,
            Tenant,
        )
        from src.store import (
            add_order,
            active_promotions_for_tenant,
            analytics_for_tenant,
            bootstrap_tenant,
            create_admin_login_token_for_tenant,
            cleanup_expired_auth_records,
            create_menu_item_for_tenant,
            create_promotion,
            get_tenant_by_slug,
            list_categories_for_tenant,
        )

        headers = {"x-admin-token": "security_regression_secret"}

        def tenant_counts(tenant_id: int) -> dict[str, int]:
            with get_session() as session:
                return {
                    "categories": session.execute(
                        select(func.count(MenuCategory.id)).where(MenuCategory.tenant_id == tenant_id)
                    ).scalar_one(),
                    "items": session.execute(
                        select(func.count(MenuItem.id)).where(MenuItem.tenant_id == tenant_id)
                    ).scalar_one(),
                    "orders": session.execute(
                        select(func.count(Order.id)).where(Order.tenant_id == tenant_id)
                    ).scalar_one(),
                    "reservations": session.execute(
                        select(func.count(Reservation.id)).where(Reservation.tenant_id == tenant_id)
                    ).scalar_one(),
                }

        def tenant_state(tenant_id: int) -> dict[str, object]:
            with get_session() as session:
                tenant_row = session.execute(select(Tenant).where(Tenant.id == tenant_id)).scalar_one()
                order_statuses = session.execute(
                    select(Order.id, Order.status).where(Order.tenant_id == tenant_id).order_by(Order.id)
                ).all()
                reservation_statuses = session.execute(
                    select(Reservation.id, Reservation.status)
                    .where(Reservation.tenant_id == tenant_id)
                    .order_by(Reservation.id)
                ).all()
                return {
                    "counts": tenant_counts(tenant_id),
                    "name": tenant_row.name,
                    "features": tenant_row.features,
                    "logo_url": tenant_row.logo_url,
                    "primary_color": tenant_row.primary_color,
                    "accent_color": tenant_row.accent_color,
                    "theme_mode": tenant_row.theme_mode,
                    "orders": [(row.id, row.status) for row in order_statuses],
                    "reservations": [(row.id, row.status) for row in reservation_statuses],
                }

        try:
            with TestClient(app) as client:
                expect("healthz", client.get("/healthz").status_code == 200)
                expect("readyz", client.get("/readyz").status_code == 200)
                with engine.connect() as connection:
                    expect("sqlite journal_mode wal", connection.execute(text("PRAGMA journal_mode")).scalar_one() == "wal")
                    expect("sqlite foreign_keys on", int(connection.execute(text("PRAGMA foreign_keys")).scalar_one()) == 1)
                    expect(
                        "sqlite busy_timeout set",
                        int(connection.execute(text("PRAGMA busy_timeout")).scalar_one()) >= 10000,
                    )
                expect("tenant page route", client.get("/t/demo").status_code == 200)
                expect(
                    "public order history entry hidden",
                    'id="orders-link" hidden' in client.get("/t/demo").text,
                )
                expect("static style available", client.get("/static/style.css").status_code == 200)
                expect("uploads traversal blocked", client.get("/uploads/%2e%2e/security.db").status_code in {400, 404})
                expect(
                    "menu images traversal blocked",
                    client.get("/menu-images/%2e%2e/security.db").status_code in {400, 404},
                )
                expect("static traversal blocked", client.get("/static/%2e%2e/src/api_app.py").status_code in {400, 404})

                bootstrap_tenant(
                    slug="demo",
                    name="Demo",
                    admin_chat_id=None,
                    bot_token=None,
                    bot_username=None,
                    bot_enabled=False,
                    features={"plan": "standard", "reservations": True},
                    category_titles=[],
                )
                tenant = get_tenant_by_slug("demo")
                category_id = list_categories_for_tenant(tenant)[0]["id"]
                item = create_menu_item_for_tenant(
                    tenant,
                    {"name": "Dish", "price": 1000, "category_id": category_id},
                )

                async def verify_order_notification_is_backgrounded() -> None:
                    original_notify_admin = api_app.notify_admin
                    calls: list[int] = []

                    async def slow_notify_admin(order_id: int, tenant_id: int) -> None:
                        await asyncio.sleep(0.2)
                        calls.append(order_id)

                    api_app.notify_admin = slow_notify_admin
                    background_tasks = BackgroundTasks()
                    request = Request(
                        {
                            "type": "http",
                            "method": "POST",
                            "path": "/t/demo/orders",
                            "headers": [],
                            "client": ("198.51.100.10", 12345),
                            "app": app,
                        }
                    )
                    started = time.perf_counter()
                    response = await create_order_by_slug(
                        "demo",
                        api_app.OrderIn.model_validate(
                            {
                                "items": [{"item_id": str(item.id), "qty": 1}],
                                "customer": {"name": "Background", "phone": "P", "address": "A"},
                            }
                        ),
                        request,
                        background_tasks,
                        x_internal_token=None,
                        tenant=tenant,
                    )
                    endpoint_elapsed = time.perf_counter() - started
                    expect("order endpoint schedules notification", len(background_tasks.tasks) == 1)
                    expect("order endpoint does not await slow notifier", endpoint_elapsed < 0.15, str(endpoint_elapsed))
                    expect("background notifier not run before response", not calls)
                    await background_tasks()
                    expect("background notifier eventually runs", calls == [response.order_id], str(calls))
                    api_app.notify_admin = original_notify_admin

                import asyncio

                asyncio.run(verify_order_notification_is_backgrounded())
                bootstrap_tenant(
                    slug="other",
                    name="Other",
                    admin_chat_id=None,
                    bot_token=None,
                    bot_username=None,
                    bot_enabled=False,
                    features={"plan": "standard", "reservations": True},
                    category_titles=[],
                )
                tenant_b = get_tenant_by_slug("other")
                category_b_id = list_categories_for_tenant(tenant_b)[0]["id"]
                item_b = create_menu_item_for_tenant(
                    tenant_b,
                    {"name": "Other Dish", "price": 2000, "category_id": category_b_id, "image_path": "other/private.png"},
                )
                with get_session() as session:
                    table = Table(tenant_id=tenant.id, name="Demo table")
                    table_b = Table(tenant_id=tenant_b.id, name="Other table")
                    session.add_all([table, table_b])
                    session.flush()
                    table_id = table.id
                    table_b_id = table_b.id

                future = (datetime.now() + timedelta(days=1)).isoformat()
                original_notify_reservation_created = api_app.notify_reservation_created

                async def failing_notify_reservation_created(*args, **kwargs):
                    raise RuntimeError("forced reservation notifier failure")

                api_app.notify_reservation_created = failing_notify_reservation_created
                reservation = client.post(
                    "/t/demo/reservations",
                    json={"name": "Guest", "phone": "+998900000000", "datetime": future, "guests": 2},
                )
                api_app.notify_reservation_created = original_notify_reservation_created
                expect("public reservation create", reservation.status_code == 200, reservation.text)
                own_table_reservation = client.post(
                    "/t/demo/reservations",
                    json={
                        "name": "Own table",
                        "phone": "+998900000000",
                        "datetime": future,
                        "guests": 2,
                        "table_id": table_id,
                    },
                )
                expect("own tenant table accepted", own_table_reservation.status_code == 200, own_table_reservation.text)
                cross_table_reservation = client.post(
                    "/t/demo/reservations",
                    json={
                        "name": "Cross table",
                        "phone": "+998900000000",
                        "datetime": future,
                        "guests": 2,
                        "table_id": table_b_id,
                    },
                )
                expect("cross-tenant table rejected", cross_table_reservation.status_code == 400, cross_table_reservation.text)
                missing_table_reservation = client.post(
                    "/t/demo/reservations",
                    json={
                        "name": "Missing table",
                        "phone": "+998900000000",
                        "datetime": future,
                        "guests": 2,
                        "table_id": 999999,
                    },
                )
                expect("missing table rejected", missing_table_reservation.status_code == 400, missing_table_reservation.text)
                rid = reservation.json().get("reservation_id")
                with get_session() as session:
                    expect(
                        "reservation persisted after notifier failure",
                        session.execute(select(Reservation).where(Reservation.id == rid)).scalar_one_or_none() is not None,
                    )
                expect("reservation list unauthorized", client.get("/t/demo/reservations").status_code == 401)
                expect(
                    "reservation update unauthorized",
                    client.patch(f"/t/demo/reservations/{rid}", json={"status": "confirmed"}).status_code == 401,
                )
                expect(
                    "reservation list authorized",
                    client.get("/t/demo/reservations", headers=headers).status_code == 200,
                )
                expect(
                    "reservation update authorized",
                    client.patch(
                        f"/t/demo/reservations/{rid}", headers=headers, json={"status": "confirmed"}
                    ).status_code
                    == 200,
                )
                invalid_reservation_status = client.patch(
                    f"/t/demo/reservations/{rid}",
                    headers=headers,
                    json={"status": "confimred"},
                )
                expect(
                    "unknown reservation status rejected",
                    invalid_reservation_status.status_code == 422,
                    invalid_reservation_status.text,
                )
                expect(
                    "known reservation status new accepted",
                    client.patch(
                        f"/t/demo/reservations/{rid}",
                        headers=headers,
                        json={"status": "new"},
                    ).status_code
                    == 200,
                )
                with TestClient(app) as operator_client:
                    operator_login = operator_client.post(
                        "/api/onboarding/operator-login", json={"secret": "security_regression_secret"}
                    )
                    expect("operator login", operator_login.status_code == 200, operator_login.text)
                    onboarded_standard = operator_client.post(
                        "/api/onboarding/tenants",
                        json={
                            "slug": "onboarded-standard",
                            "name": "Onboarded Standard",
                            "admin_chat_id": 100000010,
                            "plan": "standard",
                        },
                    )
                    expect(
                        "standard tenant onboarding",
                        onboarded_standard.status_code == 200,
                        onboarded_standard.text,
                    )
                    onboarded_tenant = get_tenant_by_slug("onboarded-standard")
                    expect(
                        "standard onboarding enables reservations",
                        bool(onboarded_tenant and (onboarded_tenant.features or {}).get("reservations")),
                    )
                    expect(
                        "operator reservation access",
                        operator_client.get("/t/demo/reservations").status_code == 200,
                    )
                    with TestClient(app) as second_operator_client:
                        second_login = second_operator_client.post(
                            "/api/onboarding/operator-login",
                            json={"secret": "security_regression_secret"},
                        )
                        expect("second operator login", second_login.status_code == 200, second_login.text)
                        expect(
                            "first operator session remains valid",
                            operator_client.get("/api/onboarding/slug-check", params={"slug": "first-session"}).status_code
                            == 200,
                        )
                        operator_logout = operator_client.post("/api/onboarding/operator-logout")
                        expect("operator logout succeeds", operator_logout.status_code == 200, operator_logout.text)
                        expect(
                            "logged-out operator session rejected",
                            operator_client.get(
                                "/api/onboarding/slug-check", params={"slug": "logged-out"}
                            ).status_code
                            == 401,
                        )
                        expect(
                            "other operator session survives logout",
                            second_operator_client.get(
                                "/api/onboarding/slug-check", params={"slug": "still-active"}
                            ).status_code
                            == 200,
                        )
                        operator_client.post(
                            "/api/onboarding/operator-login",
                            json={"secret": "security_regression_secret"},
                        )
                        expect(
                            "second operator session valid",
                            second_operator_client.get(
                                "/api/onboarding/slug-check", params={"slug": "second-session"}
                            ).status_code
                            == 200,
                        )
                    operator_token = operator_client.cookies.get("operator_session")
                    with get_session() as session:
                        session.execute(
                            update(OperatorSession)
                            .where(OperatorSession.token_hash == hashlib.sha256(operator_token.encode()).hexdigest())
                            .values(expires_at=datetime.utcnow() - timedelta(seconds=1))
                        )
                    expect(
                        "expired operator session rejected",
                        operator_client.get("/api/onboarding/slug-check", params={"slug": "expired"}).status_code == 401,
                    )
                expect(
                    "onboarding slug-check unauthorized",
                    client.get("/api/onboarding/slug-check", params={"slug": "fresh"}).status_code == 401,
                )
                expect(
                    "onboarding tenant create unauthorized",
                    client.post(
                        "/api/onboarding/tenants",
                        json={"slug": "fresh", "name": "Fresh", "admin_chat_id": 1, "plan": "basic"},
                    ).status_code
                    == 401,
                )

                invalid_reservations = [
                    {"name": "", "phone": "+998", "datetime": future, "guests": 1},
                    {"name": "Guest", "phone": " ", "datetime": future, "guests": 1},
                    {
                        "name": "Guest",
                        "phone": "+998",
                        "datetime": (datetime.now() - timedelta(days=1)).isoformat(),
                        "guests": 1,
                    },
                    {"name": "Guest", "phone": "+998", "datetime": future, "guests": 0},
                ]
                for index, payload in enumerate(invalid_reservations):
                    response = client.post("/t/demo/reservations", json=payload)
                    expect(f"invalid reservation {index}", response.status_code == 422, response.text)

                own_promotion = client.post(
                    "/t/demo/api/admin/promotions",
                    headers=headers,
                    json={"type": "item_of_the_day", "product_id": item.id, "discount_percent": 10},
                )
                expect("own tenant promotion product accepted", own_promotion.status_code == 200, own_promotion.text)
                tenant_wide_promotion = client.post(
                    "/t/demo/api/admin/promotions",
                    headers=headers,
                    json={"type": "item_of_the_day", "product_id": None, "discount_percent": 5},
                )
                expect("tenant-wide promotion accepted", tenant_wide_promotion.status_code == 200, tenant_wide_promotion.text)
                cross_promotion = client.post(
                    "/t/demo/api/admin/promotions",
                    headers=headers,
                    json={"type": "item_of_the_day", "product_id": item_b.id, "discount_percent": 10},
                )
                expect("cross-tenant promotion product rejected", cross_promotion.status_code == 400, cross_promotion.text)
                update_cross_promotion = client.patch(
                    f"/t/demo/api/admin/promotions/{own_promotion.json().get('id')}",
                    headers=headers,
                    json={"product_id": item_b.id},
                )
                expect(
                    "cross-tenant promotion product update rejected",
                    update_cross_promotion.status_code == 400,
                    update_cross_promotion.text,
                )
                invalid_day_values = ([-1], [7], ["1"], [True])
                for invalid_days in invalid_day_values:
                    invalid_days_response = client.post(
                        "/t/demo/api/admin/promotions",
                        headers=headers,
                        json={
                            "type": "happy_hours",
                            "days_of_week": invalid_days,
                            "start_time": "10:00:00",
                            "end_time": "11:00:00",
                        },
                    )
                    expect(
                        f"invalid promotion days rejected {invalid_days}",
                        invalid_days_response.status_code == 422,
                        invalid_days_response.text,
                    )
                normalized_days = client.post(
                    "/t/demo/api/admin/promotions",
                    headers=headers,
                    json={
                        "type": "happy_hours",
                        "days_of_week": [2, 1, 2],
                        "start_time": "10:00:00",
                        "end_time": "11:00:00",
                    },
                )
                expect("valid promotion days accepted", normalized_days.status_code == 200, normalized_days.text)
                expect(
                    "promotion days normalized",
                    normalized_days.json().get("days_of_week") == [1, 2],
                    normalized_days.text,
                )

                invalid_timezone = client.patch(
                    "/t/demo/api/admin/tenant",
                    headers=headers,
                    json={"timezone": "Not/A_Timezone"},
                )
                expect("invalid tenant timezone rejected", invalid_timezone.status_code == 422, invalid_timezone.text)
                valid_timezone = client.patch(
                    "/t/demo/api/admin/tenant",
                    headers=headers,
                    json={"timezone": "Asia/Tashkent"},
                )
                expect("valid tenant timezone accepted", valid_timezone.status_code == 200, valid_timezone.text)

                happy_hour = create_promotion(
                    tenant,
                    {
                        "type": "happy_hours",
                        "discount_percent": 10,
                        "start_time": dt_time(14, 0),
                        "end_time": dt_time(16, 0),
                        "days_of_week": [0],
                    },
                )
                monday_utc = datetime(2026, 7, 20, 10, 0, tzinfo=timezone.utc)
                expect(
                    "happy hour uses tenant local time",
                    happy_hour.id in {promo.id for promo in active_promotions_for_tenant(tenant, monday_utc)},
                )
                outside_utc = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)
                expect(
                    "happy hour inactive outside tenant local window",
                    happy_hour.id not in {promo.id for promo in active_promotions_for_tenant(tenant, outside_utc)},
                )
                overnight = create_promotion(
                    tenant,
                    {
                        "type": "happy_hours",
                        "discount_percent": 10,
                        "start_time": dt_time(23, 0),
                        "end_time": dt_time(2, 0),
                        "days_of_week": [1],
                    },
                )
                tuesday_local_0100 = datetime(2026, 7, 20, 20, 0, tzinfo=timezone.utc)
                expect(
                    "happy hour window crossing midnight works",
                    overnight.id
                    in {promo.id for promo in active_promotions_for_tenant(tenant, tuesday_local_0100)},
                )

                base_order = {
                    "items": [{"item_id": str(item.id), "qty": 1}],
                    "customer": {"name": "Customer", "phone": "+998900000001", "address": "Address"},
                }

                bootstrap_tenant(
                    slug="metrics",
                    name="Metrics",
                    admin_chat_id=None,
                    bot_token=None,
                    bot_username=None,
                    bot_enabled=False,
                    features={"plan": "standard"},
                    category_titles=[],
                )
                metrics_tenant = get_tenant_by_slug("metrics")
                metrics_category = list_categories_for_tenant(metrics_tenant)[0]["id"]
                metric_items = [
                    create_menu_item_for_tenant(
                        metrics_tenant,
                        {"name": name, "price": price, "category_id": metrics_category},
                    )
                    for name, price in (("Completed item", 100), ("New item", 200), ("Canceled item", 300))
                ]
                metric_order_ids = [
                    add_order(
                        {
                            "items": [{"item_id": str(metric_item.id), "qty": 1}],
                            "customer": {"name": "Metric", "phone": "P", "address": "A"},
                            "source": "site",
                        },
                        metrics_tenant,
                    )
                    for metric_item in metric_items
                ]
                with get_session() as session:
                    session.execute(
                        update(Order).where(Order.id == metric_order_ids[0]).values(status="COMPLETED")
                    )
                    session.execute(
                        update(Order).where(Order.id == metric_order_ids[2]).values(status="CANCELED")
                    )
                metrics = analytics_for_tenant(metrics_tenant, "7d")
                expect("analytics counts qualifying orders", metrics["orders"] == 1, str(metrics))
                expect("analytics revenue uses qualifying orders", metrics["revenue"] == 100, str(metrics))
                expect("analytics average uses qualifying count", metrics["average_check"] == 100, str(metrics))
                expect(
                    "analytics top items use qualifying orders",
                    [row["name"] for row in metrics["top_items"]] == ["Completed item"],
                    str(metrics),
                )

                bootstrap_tenant(
                    slug="metrics-zero",
                    name="Metrics Zero",
                    admin_chat_id=None,
                    bot_token=None,
                    bot_username=None,
                    bot_enabled=False,
                    features={"plan": "standard"},
                    category_titles=[],
                )
                zero_metrics = analytics_for_tenant(get_tenant_by_slug("metrics-zero"), "7d")
                expect("analytics zero completed average", zero_metrics["average_check"] == 0, str(zero_metrics))
                original_notify_admin = api_app.notify_admin

                async def failing_notify_admin(*args, **kwargs):
                    raise RuntimeError("forced order notifier failure")

                api_app.notify_admin = failing_notify_admin
                spoofed = client.post(
                    "/t/demo/orders",
                    json={
                        **base_order,
                        "source": "bot",
                        "customer_chat_id": 1,
                        "tenant_id": tenant_b.id,
                        "admin_chat_id": 999,
                        "status": "COMPLETED",
                    },
                )
                api_app.notify_admin = original_notify_admin
                expect("spoofed source order", spoofed.status_code == 200, spoofed.text)
                with get_session() as session:
                    stored = session.execute(select(Order).where(Order.id == spoofed.json()["order_id"])).scalar_one()
                    expect(
                        "spoofed source ignored",
                        stored.source == "site"
                        and stored.customer_chat_id is None
                        and stored.tenant_id == tenant.id
                        and stored.status == "NEW",
                    )
                    expect(
                        "single order created after notifier failure",
                        session.execute(select(func.count(Order.id)).where(Order.id == spoofed.json()["order_id"])).scalar_one() == 1,
                    )

                trusted = client.post(
                    "/t/demo/orders",
                    headers={"x-internal-token": "security_regression_secret"},
                    json={**base_order, "source": "site", "customer_chat_id": 123},
                )
                expect("trusted bot order", trusted.status_code == 200, trusted.text)
                with get_session() as session:
                    stored = session.execute(select(Order).where(Order.id == trusted.json()["order_id"])).scalar_one()
                    expect("trusted source accepted", stored.source == "bot" and stored.customer_chat_id == 123)

                invalid_orders = [
                    {**base_order, "customer": {"name": "", "phone": "+998", "address": "Address"}},
                    {**base_order, "customer": {"name": "Customer", "phone": " ", "address": "Address"}},
                    {**base_order, "customer": {"name": "X" * 256, "phone": "+998", "address": "Address"}},
                    {**base_order, "customer": {"name": "Customer", "phone": "+998", "address": "X" * 2001}},
                ]
                for index, payload in enumerate(invalid_orders):
                    response = client.post("/t/demo/orders", json=payload)
                    expect(f"invalid order {index}", response.status_code == 422, response.text)

                history = client.get("/t/demo/api/orders/history", params={"phone": "+998900000001"})
                expect("order history disabled", history.status_code == 403, history.text)
                expect("order history body private", "items" not in history.text, history.text)
                with get_session() as session:
                    order_count_before = session.execute(
                        select(func.count(Order.id)).where(Order.tenant_id == tenant.id)
                    ).scalar_one()
                reorder = client.post(
                    f"/t/demo/api/orders/{spoofed.json()['order_id']}/reorder",
                    params={"phone": "+998900000001"},
                )
                expect("old reorder URL removed", reorder.status_code in {404, 405}, reorder.text)
                expect("reorder body private", "order_id" not in reorder.text, reorder.text)
                with get_session() as session:
                    order_count_after = session.execute(
                        select(func.count(Order.id)).where(Order.tenant_id == tenant.id)
                    ).scalar_one()
                expect("old reorder URL does not create order", order_count_after == order_count_before)

                files_before_invalid = len(list((tmp_path / "menu_images").rglob("*.*")))
                fake_image = client.post(
                    "/admin/upload-image/demo",
                    headers=headers,
                    files={"file": ("fake.png", b"not an image", "image/png")},
                )
                expect("fake image rejected", fake_image.status_code == 400, fake_image.text)
                expect(
                    "fake image leaves no file",
                    len(list((tmp_path / "menu_images").rglob("*.*"))) == files_before_invalid,
                )
                svg = client.post(
                    "/admin/upload-image/demo",
                    headers=headers,
                    files={"file": ("image.svg", b"<svg><script>alert(1)</script></svg>", "image/svg+xml")},
                )
                expect("svg rejected", svg.status_code == 400, svg.text)
                oversized = client.post(
                    "/admin/upload-image/demo",
                    headers=headers,
                    files={"file": ("large.png", b"\x89PNG\r\n\x1a\n" + b"0" * (5 * 1024 * 1024), "image/png")},
                )
                expect("oversized image rejected", oversized.status_code == 413, oversized.text)
                valid_png = base64.b64decode(
                    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
                )
                valid_image = client.post(
                    "/admin/upload-image/demo",
                    headers=headers,
                    files={"file": ("image.txt", valid_png, "text/plain")},
                )
                expect("signature-based image accepted", valid_image.status_code == 200, valid_image.text)
                original_to_thread = api_app.asyncio.to_thread
                to_thread_calls: list[str] = []

                async def tracking_to_thread(function, *args, **kwargs):
                    to_thread_calls.append(function.__name__)
                    return await original_to_thread(function, *args, **kwargs)

                api_app.asyncio.to_thread = tracking_to_thread
                threaded_upload = client.post(
                    "/admin/upload-image/demo",
                    headers=headers,
                    files={"file": ("threaded.png", valid_png, "image/png")},
                )
                api_app.asyncio.to_thread = original_to_thread
                expect("threaded image upload succeeds", threaded_upload.status_code == 200, threaded_upload.text)
                expect("image disk write moved off event loop", "_atomic_write" in to_thread_calls, str(to_thread_calls))

                original_replace = api_app.os.replace

                def failing_replace(*_args, **_kwargs):
                    raise OSError("forced replace failure")

                api_app.os.replace = failing_replace
                try:
                    try:
                        client.post(
                            "/admin/upload-image/demo",
                            headers=headers,
                            files={"file": ("failed.png", valid_png, "image/png")},
                        )
                    except OSError:
                        pass
                finally:
                    api_app.os.replace = original_replace
                expect(
                    "failed upload leaves no partial file",
                    not any(path.name.startswith(".upload-") for path in (tmp_path / "menu_images").rglob("*")),
                )
                rate_limiter._events.clear()
                rate_limiter._windows.clear()
                files_before_limit = len(list((tmp_path / "menu_images").rglob("*.*")))
                upload_statuses = [
                    client.post(
                        "/admin/upload-image/demo",
                        headers=headers,
                        files={"file": (f"limited-{index}.png", valid_png, "image/png")},
                    ).status_code
                    for index in range(11)
                ]
                expect("upload rate limit allows ten", upload_statuses[:10] == [200] * 10, str(upload_statuses))
                expect("upload rate limit rejects eleventh", upload_statuses[-1] == 429, str(upload_statuses))
                expect(
                    "rejected upload creates no file",
                    len(list((tmp_path / "menu_images").rglob("*.*"))) == files_before_limit + 10,
                )
                with TestClient(app) as tenant_admin_client:
                    login_token = create_admin_login_token_for_tenant(tenant).token
                    login = tenant_admin_client.post(
                        "/admin/auth/login", json={"token": login_token, "slug": "demo"}
                    )
                    expect("tenant admin login", login.status_code == 200, login.text)
                    with TestClient(app) as second_admin_client:
                        second_admin_token = create_admin_login_token_for_tenant(tenant).token
                        second_admin_login = second_admin_client.post(
                            "/admin/auth/login", json={"token": second_admin_token, "slug": "demo"}
                        )
                        expect("second tenant admin login", second_admin_login.status_code == 200, second_admin_login.text)
                        admin_logout = tenant_admin_client.post("/admin/auth/logout")
                        expect("admin logout succeeds", admin_logout.status_code == 200, admin_logout.text)
                        expect(
                            "logged-out admin rejected",
                            tenant_admin_client.get("/t/demo/api/admin/promotions").status_code == 401,
                        )
                        expect(
                            "other admin session survives logout",
                            second_admin_client.get("/t/demo/api/admin/promotions").status_code == 200,
                        )
                        replacement_token = create_admin_login_token_for_tenant(tenant).token
                        tenant_admin_client.post(
                            "/admin/auth/login", json={"token": replacement_token, "slug": "demo"}
                        )
                    expect(
                        "tenant admin is not operator",
                        tenant_admin_client.get("/api/onboarding/slug-check", params={"slug": "x"}).status_code == 401,
                    )

                    blocked_image_path = tenant_admin_client.post(
                        "/admin/api/menu/demo",
                        json={
                            "name": "Blocked Image",
                            "price": 100,
                            "category_id": category_id,
                            "image_path": "other/private.png",
                        },
                    )
                    expect("cross-tenant image path rejected", blocked_image_path.status_code == 400, blocked_image_path.text)
                    expect(
                        "cross-tenant image path creates no file",
                        len(list((tmp_path / "menu_images").rglob("*.*"))) == files_before_limit + 10,
                    )
                    traversal_image_path = tenant_admin_client.post(
                        "/admin/api/menu/demo",
                        json={
                            "name": "Traversal Image",
                            "price": 100,
                            "category_id": category_id,
                            "image_path": "../private.png",
                        },
                    )
                    expect("menu image path traversal rejected", traversal_image_path.status_code == 400, traversal_image_path.text)
                    expect(
                        "failed uploads leave no temp files",
                        not any(path.name.startswith(".readyz-") for path in (tmp_path / "uploads").rglob("*")),
                    )
                    expect(
                        "tenant admin cannot upload menu image for tenant B",
                        tenant_admin_client.post(
                            "/admin/upload-image/other",
                            files={"file": ("image.png", valid_png, "image/png")},
                        ).status_code
                        in {401, 403, 404},
                    )
                    expect(
                        "tenant admin cannot replace tenant B upload",
                        tenant_admin_client.post(
                            "/t/other/api/admin/upload",
                            data={"type": "menu"},
                            files={"file": ("image.png", valid_png, "image/png")},
                        ).status_code
                        in {401, 403, 404},
                    )

                    rate_limiter._events.clear()
                    rate_limiter._windows.clear()
                    first_upload = tenant_admin_client.post(
                        "/admin/upload-image/demo",
                        files={"file": ("first.png", valid_png, "image/png")},
                    )
                    second_upload = tenant_admin_client.post(
                        "/admin/upload-image/demo",
                        files={"file": ("second.png", valid_png, "image/png")},
                    )
                    expect("managed menu uploads created", first_upload.status_code == 200 and second_upload.status_code == 200)
                    first_path = first_upload.json()["image_path"]
                    second_path = second_upload.json()["image_path"]
                    shared_item = tenant_admin_client.post(
                        "/admin/api/menu/demo",
                        json={
                            "name": "Shared image",
                            "price": 100,
                            "category_id": category_id,
                            "image_path": first_path,
                        },
                    )
                    replace_item = tenant_admin_client.post(
                        "/admin/api/menu/demo",
                        json={
                            "name": "Replace image",
                            "price": 100,
                            "category_id": category_id,
                            "image_path": first_path,
                        },
                    )
                    replacement = tenant_admin_client.put(
                        f"/admin/api/menu/demo/{replace_item.json().get('id')}",
                        json={
                            "name": "Replace image",
                            "price": 100,
                            "category_id": category_id,
                            "image_path": second_path,
                        },
                    )
                    expect("menu image replacement succeeds", replacement.status_code == 200, replacement.text)
                    first_file = tmp_path / "menu_images" / first_path
                    expect("shared managed image retained", first_file.is_file())
                    shared_delete = tenant_admin_client.delete(
                        f"/admin/api/menu/demo/{shared_item.json().get('id')}"
                    )
                    expect("shared image item delete succeeds", shared_delete.status_code == 200, shared_delete.text)
                    expect("last managed image reference deletion removes file", not first_file.exists())

                    failure_upload = tenant_admin_client.post(
                        "/admin/upload-image/demo",
                        files={"file": ("delete-failure.png", valid_png, "image/png")},
                    )
                    failure_item = tenant_admin_client.post(
                        "/admin/api/menu/demo",
                        json={
                            "name": "Delete failure",
                            "price": 100,
                            "category_id": category_id,
                            "image_path": failure_upload.json()["image_path"],
                        },
                    )
                    original_unlink = Path.unlink

                    def failing_unlink(self, *args, **kwargs):
                        raise OSError("forced unlink failure")

                    Path.unlink = failing_unlink
                    try:
                        deletion_failure_update = tenant_admin_client.put(
                            f"/admin/api/menu/demo/{failure_item.json().get('id')}",
                            json={
                                "name": "Delete failure",
                                "price": 100,
                                "category_id": category_id,
                                "image_path": None,
                            },
                        )
                    finally:
                        Path.unlink = original_unlink
                    expect(
                        "managed image delete failure does not break update",
                        deletion_failure_update.status_code == 200,
                        deletion_failure_update.text,
                    )

                    static_asset = BASE_DIR / "static" / "demo" / "menu" / "fries.webp"
                    static_item = create_menu_item_for_tenant(
                        tenant,
                        {
                            "name": "Static asset",
                            "price": 100,
                            "category_id": category_id,
                            "image_path": "static/demo/menu/fries.webp",
                        },
                    )
                    static_delete = tenant_admin_client.delete(
                        f"/admin/api/menu/demo/{static_item.id}"
                    )
                    expect("static-backed item delete succeeds", static_delete.status_code == 200, static_delete.text)
                    expect("static asset is never deleted", static_asset.is_file())

                    rate_limiter._events.clear()
                    rate_limiter._windows.clear()
                    hero_one = tenant_admin_client.post(
                        "/t/demo/api/admin/upload",
                        data={"type": "hero"},
                        files={"file": ("hero-one.png", valid_png, "image/png")},
                    )
                    hero_two = tenant_admin_client.post(
                        "/t/demo/api/admin/upload",
                        data={"type": "hero"},
                        files={"file": ("hero-two.png", valid_png, "image/png")},
                    )
                    tenant_admin_client.patch(
                        "/t/demo/api/admin/tenant",
                        json={"hero_image": hero_one.json()["url"]},
                    )
                    hero_replace = tenant_admin_client.patch(
                        "/t/demo/api/admin/tenant",
                        json={"hero_image": hero_two.json()["url"]},
                    )
                    expect("hero replacement succeeds", hero_replace.status_code == 200, hero_replace.text)
                    hero_one_name = hero_one.json()["url"].rsplit("/", 1)[-1]
                    expect(
                        "replaced managed hero removed",
                        not (tmp_path / "uploads" / "demo" / "hero" / hero_one_name).exists(),
                    )

                    reservation_b = client.post(
                        "/t/other/reservations",
                        json={"name": "Other Guest", "phone": "+998900000002", "datetime": future, "guests": 2},
                    )
                    expect("tenant B reservation setup", reservation_b.status_code == 200, reservation_b.text)
                    order_b_id = add_order(
                        {
                            "items": [{"item_id": str(item_b.id), "qty": 1}],
                            "customer": {"name": "Other Customer", "phone": "+998900000003", "address": "Other Address"},
                            "source": "site",
                        },
                        tenant=tenant_b,
                    )
                    before_b = tenant_state(tenant_b.id)
                    blocked_requests = [
                        ("tenant B category create blocked", tenant_admin_client.post("/t/other/categories", json={"title": "Blocked"})),
                        (
                            "tenant B category update blocked",
                            tenant_admin_client.patch(
                                f"/t/other/categories/{category_b_id}", json={"title": "Blocked"}
                            ),
                        ),
                        (
                            "tenant B category delete blocked",
                            tenant_admin_client.delete(f"/t/other/categories/{category_b_id}"),
                        ),
                        (
                            "tenant B menu create blocked",
                            tenant_admin_client.post(
                                "/admin/api/menu/other",
                                json={"name": "Blocked", "price": 1, "category_id": category_b_id},
                            ),
                        ),
                        (
                            "tenant B menu update blocked",
                            tenant_admin_client.put(
                                f"/admin/api/menu/other/{item_b.id}",
                                json={"name": "Blocked", "price": 1, "category_id": category_b_id},
                            ),
                        ),
                        (
                            "tenant B menu delete blocked",
                            tenant_admin_client.delete(f"/admin/api/menu/other/{item_b.id}"),
                        ),
                        (
                            "tenant B settings update blocked",
                            tenant_admin_client.patch("/t/other/api/admin/tenant", json={"description": "Blocked"}),
                        ),
                        (
                            "tenant B order update blocked",
                            tenant_admin_client.patch(
                                f"/t/other/api/admin/orders/{order_b_id}/status", json={"status": "ACCEPTED"}
                            ),
                        ),
                        ("tenant B reservations read blocked", tenant_admin_client.get("/t/other/reservations")),
                        (
                            "tenant B reservation update blocked",
                            tenant_admin_client.patch(
                                f"/t/other/reservations/{reservation_b.json()['reservation_id']}",
                                json={"status": "confirmed"},
                            ),
                        ),
                    ]
                    for label, response in blocked_requests:
                        expect(label, response.status_code in {401, 403, 404}, response.text)
                    expect("tenant B unchanged after blocked requests", tenant_state(tenant_b.id) == before_b)

                status_order_id = add_order(
                    {
                        "items": [{"item_id": str(item.id), "qty": 1}],
                        "customer": {"name": "Status Customer", "phone": "+998900000004", "address": "Address"},
                        "source": "site",
                    },
                    tenant=tenant,
                )
                original_notify_order_status_changed = api_app.notify_order_status_changed

                async def failing_notify_order_status_changed(*args, **kwargs):
                    raise RuntimeError("forced status notifier failure")

                api_app.notify_order_status_changed = failing_notify_order_status_changed
                status_response = client.patch(
                    f"/t/demo/api/admin/orders/{status_order_id}/status",
                    headers=headers,
                    json={"status": "ACCEPTED"},
                )
                api_app.notify_order_status_changed = original_notify_order_status_changed
                expect("status update succeeds after notifier failure", status_response.status_code == 200, status_response.text)
                with get_session() as session:
                    stored_status = session.execute(select(Order.status).where(Order.id == status_order_id)).scalar_one()
                expect("status persisted after notifier failure", stored_status == "ACCEPTED", stored_status)

                class FailingEngine:
                    def connect(self):
                        raise SQLAlchemyError("forced db failure")

                original_engine = api_app.engine
                api_app.engine = FailingEngine()
                db_failed_readyz = client.get("/readyz")
                api_app.engine = original_engine
                expect("readyz db failure returns 503", db_failed_readyz.status_code == 503, db_failed_readyz.text)

                original_writable_check = api_app._check_directory_writable
                api_app._check_directory_writable = lambda path: (_ for _ in ()).throw(OSError("forced storage failure"))
                storage_failed_readyz = client.get("/readyz")
                api_app._check_directory_writable = original_writable_check
                expect("readyz storage failure returns 503", storage_failed_readyz.status_code == 503, storage_failed_readyz.text)

                try:
                    with get_session() as session:
                        session.add(
                            Tenant(
                                slug="rollback-demo",
                                name="Rollback Demo",
                                admin_chat_id=None,
                                bot_enabled=False,
                                features={},
                                is_active=True,
                            )
                        )
                        raise RuntimeError("forced rollback")
                except RuntimeError:
                    pass
                with get_session() as session:
                    rolled_back = session.execute(select(Tenant).where(Tenant.slug == "rollback-demo")).scalar_one_or_none()
                expect("sqlite transaction rollback", rolled_back is None)

                token = create_admin_login_token_for_tenant(tenant).token
                wrong_slug_login = client.post(
                    "/admin/auth/login", json={"token": token, "slug": "other"}
                )
                expect("wrong slug login rejected", wrong_slug_login.status_code == 401, wrong_slug_login.text)
                correct_after_wrong_slug = client.post(
                    "/admin/auth/login", json={"token": token, "slug": "demo"}
                )
                expect(
                    "wrong slug does not consume login token",
                    correct_after_wrong_slug.status_code == 200,
                    correct_after_wrong_slug.text,
                )

                token = create_admin_login_token_for_tenant(tenant).token
                session_count_before = 0
                with get_session() as session:
                    session_count_before = session.execute(select(func.count(AdminSession.id))).scalar_one()

                def login_once() -> int:
                    return client.post(
                        "/admin/auth/login", json={"token": token, "slug": "demo"}
                    ).status_code

                with concurrent.futures.ThreadPoolExecutor(max_workers=12) as executor:
                    statuses = list(executor.map(lambda _: login_once(), range(12)))
                expect("single token success", statuses.count(200) == 1, str(statuses))
                expect("single token failures", statuses.count(401) == 11, str(statuses))
                with get_session() as session:
                    session_count_after = session.execute(select(func.count(AdminSession.id))).scalar_one()
                expect("single admin session created", session_count_after - session_count_before == 1)

                inactive_token = create_admin_login_token_for_tenant(tenant_b).token
                with get_session() as session:
                    session.execute(update(Tenant).where(Tenant.id == tenant_b.id).values(is_active=False))
                    inactive_session_count_before = session.execute(select(func.count(AdminSession.id))).scalar_one()
                inactive_login = client.post("/admin/auth/login", json={"token": inactive_token, "slug": "other"})
                expect("inactive tenant login token returns 401", inactive_login.status_code == 401, inactive_login.text)
                inactive_login_retry = client.post("/admin/auth/login", json={"token": inactive_token, "slug": "other"})
                expect("inactive tenant login token cannot be reused", inactive_login_retry.status_code == 401, inactive_login_retry.text)
                with get_session() as session:
                    inactive_session_count_after = session.execute(select(func.count(AdminSession.id))).scalar_one()
                    inactive_used = session.execute(
                        select(AdminLoginToken.used).where(
                            AdminLoginToken.token == hashlib.sha256(inactive_token.encode()).hexdigest()
                        )
                    ).scalar_one()
                expect(
                    "inactive tenant login token creates no session",
                    inactive_session_count_after == inactive_session_count_before,
                )
                expect("inactive tenant login token consumed", inactive_used is True)

                rate_limiter._events.clear()
                statuses = [client.post("/t/demo/orders", json=base_order).status_code for _ in range(31)]
                expect("order rate limit", statuses[-1] == 429, str(statuses[-3:]))

                rate_limiter._events.clear()
                operator_statuses = [
                    client.post("/api/onboarding/operator-login", json={"secret": "wrong"}).status_code
                    for _ in range(11)
                ]
                expect("operator login rate limit", operator_statuses[-1] == 429, str(operator_statuses))

                rate_limiter._events.clear()
                admin_statuses = [
                    client.post("/admin/auth/login", json={"token": "wrong", "slug": "demo"}).status_code
                    for _ in range(21)
                ]
                expect("admin login rate limit", admin_statuses[-1] == 429, str(admin_statuses[-3:]))

                cleanup_now = datetime.utcnow()
                with get_session() as session:
                    session.add(
                        AdminSession(
                            tenant_id=tenant.id,
                            session_token="cleanup-expired-admin",
                            created_at=cleanup_now - timedelta(days=2),
                            expires_at=cleanup_now - timedelta(seconds=1),
                        )
                    )
                    session.add(
                        AdminSession(
                            tenant_id=tenant.id,
                            session_token="cleanup-active-admin",
                            created_at=cleanup_now,
                            expires_at=cleanup_now + timedelta(days=1),
                        )
                    )
                    session.add(
                        AdminLoginToken(
                            tenant_id=tenant.id,
                            token="cleanup-used-token",
                            used=True,
                            created_at=cleanup_now - timedelta(days=2),
                            expires_at=cleanup_now + timedelta(days=1),
                        )
                    )
                cleanup_counts = cleanup_expired_auth_records(cleanup_now)
                expect("expired admin session cleaned", cleanup_counts["admin_sessions"] >= 1)
                expect("old used login token cleaned", cleanup_counts["login_tokens"] >= 1)
                with get_session() as session:
                    expect(
                        "active admin session preserved",
                        session.execute(
                            select(AdminSession).where(AdminSession.session_token == "cleanup-active-admin")
                        ).scalar_one_or_none()
                        is not None,
                    )

                limiter = InMemoryRateLimiter()
                limiter._events["expired"].append(1.0)
                limiter._windows["expired"] = 60
                limiter._events["active"].append(995.0)
                limiter._windows["active"] = 60
                removed = limiter.cleanup_expired(now=1000.0)
                expect("expired limiter bucket removed", removed == 1, str(removed))
                expect("empty limiter key removed", "expired" not in limiter._events)
                expect("active limiter bucket preserved", "active" in limiter._events)
                rotating_limiter = InMemoryRateLimiter()
                for index in range(256):
                    rotating_limiter._events[f"active-{index}"].append(995.0)
                    rotating_limiter._windows[f"active-{index}"] = 60
                rotating_limiter._events["expired-after-active"].append(1.0)
                rotating_limiter._windows["expired-after-active"] = 60
                rotating_limiter.cleanup_expired(now=1000.0, max_keys=256)
                rotating_limiter.cleanup_expired(now=1000.0, max_keys=256)
                expect(
                    "bounded limiter cleanup advances past active buckets",
                    "expired-after-active" not in rotating_limiter._events,
                )
        finally:
            engine.dispose()

    print(json.dumps({"status": "ok" if not issues else "failed", "issues": issues}, indent=2))
    if issues:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
