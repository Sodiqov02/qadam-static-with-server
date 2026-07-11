from __future__ import annotations

import concurrent.futures
import base64
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

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
        from src.api_app import app, rate_limiter
        from src.db import engine, get_session
        from src.db_models import AdminLoginToken, AdminSession, MenuCategory, MenuItem, Order, Reservation, Tenant
        from src.store import (
            add_order,
            bootstrap_tenant,
            create_admin_login_token_for_tenant,
            create_menu_item_for_tenant,
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
                with TestClient(app) as operator_client:
                    operator_login = operator_client.post(
                        "/api/onboarding/operator-login", json={"secret": "security_regression_secret"}
                    )
                    expect("operator login", operator_login.status_code == 200, operator_login.text)
                    expect(
                        "operator reservation access",
                        operator_client.get("/t/demo/reservations").status_code == 200,
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

                base_order = {
                    "items": [{"item_id": str(item.id), "qty": 1}],
                    "customer": {"name": "Customer", "phone": "+998900000001", "address": "Address"},
                }
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
                rate_limiter._events.clear()
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
                        select(AdminLoginToken.used).where(AdminLoginToken.token == inactive_token)
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
        finally:
            engine.dispose()

    print(json.dumps({"status": "ok" if not issues else "failed", "issues": issues}, indent=2))
    if issues:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
