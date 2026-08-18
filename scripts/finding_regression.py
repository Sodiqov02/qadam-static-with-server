from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import sys
import tempfile


BASE_DIR = Path(__file__).resolve().parents[1]
ADMIN_SECRET = "finding_regression_admin_secret"
FEATURES = {
    "plan": "vip",
    "analytics": True,
    "promotions": True,
    "reservations": True,
}
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))


def require(label: str, condition: bool, detail: object = "") -> None:
    if not condition:
        raise AssertionError(f"{label}: {detail}".rstrip())


def run_finding(name: str, scenario) -> None:
    try:
        scenario()
    except Exception as exc:
        print(json.dumps({"status": "failed", "finding": name, "error": f"{type(exc).__name__}: {exc}"}, indent=2))
        raise SystemExit(1)
    print(json.dumps({"status": "ok", "finding": name, "issues": []}, indent=2))


@contextmanager
def isolated_app():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db_path = Path(tmp) / "finding.db"
        os.environ["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
        os.environ["ADMIN_SECRET"] = ADMIN_SECRET
        os.environ["API_BASE_URL"] = "http://127.0.0.1:8000"
        os.environ["UPLOADS_DIR"] = str(Path(tmp) / "uploads")
        os.environ["MENU_IMAGES_DIR"] = str(Path(tmp) / "menu_images")
        for key in ("APP_ENV", "ENVIRONMENT", "QADAM_ENV", "ENV", "RAILWAY_ENVIRONMENT"):
            os.environ.pop(key, None)

        from fastapi.testclient import TestClient
        from src.api_app import app
        from src.db import engine

        try:
            with TestClient(app) as client:
                yield client, app
        finally:
            engine.dispose()


def create_tenant(slug: str):
    from src.store import bootstrap_tenant, get_tenant_by_slug

    bootstrap_tenant(
        slug=slug,
        name=slug.title(),
        admin_chat_id=1,
        bot_token=None,
        bot_username=None,
        bot_enabled=False,
        features=FEATURES,
        category_titles=["Main"],
    )
    tenant = get_tenant_by_slug(slug)
    require(f"{slug} tenant created", tenant is not None)
    return tenant


def scenario_operator_multi_session() -> None:
    from fastapi.testclient import TestClient

    with isolated_app() as (first, app):
        with TestClient(app) as second:
            require(
                "first operator login",
                first.post("/api/onboarding/operator-login", json={"secret": ADMIN_SECRET}).status_code == 200,
            )
            require(
                "second operator login",
                second.post("/api/onboarding/operator-login", json={"secret": ADMIN_SECRET}).status_code == 200,
            )
            first_status = first.get("/api/onboarding/slug-check", params={"slug": "first-session"}).status_code
            second_status = second.get("/api/onboarding/slug-check", params={"slug": "second-session"}).status_code
            require("first session survives second login", first_status == 200, first_status)
            require("second session remains valid", second_status == 200, second_status)


def scenario_reservation_tenant_isolation() -> None:
    with isolated_app() as (client, _):
        tenant = create_tenant("reservation-a")
        other = create_tenant("reservation-b")
        from src.db import get_session
        from src.db_models import Table

        with get_session() as session:
            foreign_table = Table(tenant_id=other.id, name="Foreign")
            session.add(foreign_table)
            session.flush()
            foreign_table_id = foreign_table.id

        response = client.post(
            "/t/reservation-a/reservations",
            json={
                "name": "Guest",
                "phone": "+998900000000",
                "datetime": (datetime.now() + timedelta(days=1)).isoformat(),
                "guests": 2,
                "table_id": foreign_table_id,
            },
        )
        require("cross-tenant reservation table rejected", response.status_code == 400, response.text)


def scenario_promotion_tenant_isolation() -> None:
    with isolated_app() as (client, _):
        tenant = create_tenant("promotion-a")
        other = create_tenant("promotion-b")
        from src.store import create_menu_item_for_tenant, list_categories_for_tenant

        category_id = list_categories_for_tenant(other)[0]["id"]
        foreign_item = create_menu_item_for_tenant(
            other,
            {"name": "Foreign dish", "price": 100, "category_id": category_id},
        )
        response = client.post(
            "/t/promotion-a/api/admin/promotions",
            headers={"x-admin-token": ADMIN_SECRET},
            json={
                "type": "item_of_the_day",
                "is_active": True,
                "product_id": foreign_item.id,
                "discount_percent": 10,
            },
        )
        require("cross-tenant promotion product rejected", response.status_code == 400, response.text)


def scenario_wrong_slug_token_atomicity() -> None:
    with isolated_app() as (client, _):
        tenant = create_tenant("token-a")
        create_tenant("token-b")
        from src.store import create_admin_login_token_for_tenant

        token = create_admin_login_token_for_tenant(tenant).token
        wrong = client.post("/admin/auth/login", json={"token": token, "slug": "token-b"})
        correct = client.post("/admin/auth/login", json={"token": token, "slug": "token-a"})
        require("wrong slug rejected", wrong.status_code == 401, wrong.text)
        require("wrong slug does not consume token", correct.status_code == 200, correct.text)


def scenario_analytics_consistency() -> None:
    with isolated_app():
        tenant = create_tenant("analytics")
        from src.db import get_session
        from src.db_models import Order
        from src.store import analytics_for_tenant

        with get_session() as session:
            session.add_all(
                [
                    Order(
                        tenant_id=tenant.id,
                        status="COMPLETED",
                        items=[{"item_id": "dish", "qty": 1, "price_at_order": 100}],
                        total=Decimal("100"),
                    ),
                    Order(
                        tenant_id=tenant.id,
                        status="NEW",
                        items=[{"item_id": "ignored", "qty": 10, "price_at_order": 500}],
                        total=Decimal("5000"),
                    ),
                ]
            )
        metrics = analytics_for_tenant(tenant, "7d")
        require("completed-order count", metrics["orders"] == 1, metrics)
        require("completed-order revenue", metrics["revenue"] == 100, metrics)
        require("completed-order average", metrics["average_check"] == 100, metrics)
        require("completed-order top items", [item["item_id"] for item in metrics["top_items"]] == ["dish"], metrics)


def scenario_reservation_status_validation() -> None:
    with isolated_app() as (client, _):
        create_tenant("status")
        created = client.post(
            "/t/status/reservations",
            json={
                "name": "Guest",
                "phone": "+998900000000",
                "datetime": (datetime.now() + timedelta(days=1)).isoformat(),
                "guests": 2,
            },
        )
        require("reservation created", created.status_code == 200, created.text)
        response = client.patch(
            f"/t/status/reservations/{created.json()['reservation_id']}",
            headers={"x-admin-token": ADMIN_SECRET},
            json={"status": "confimred"},
        )
        require("unknown reservation status rejected", response.status_code == 422, response.text)


def scenario_tenant_timezone_happy_hours() -> None:
    with isolated_app():
        tenant = create_tenant("timezone")
        tenant.timezone = "Asia/Tashkent"
        from src.store import active_promotions_for_tenant, create_promotion

        create_promotion(
            tenant,
            {
                "type": "happy_hours",
                "is_active": True,
                "discount_percent": 10,
                "start_time": time(14, 0),
                "end_time": time(16, 0),
                "days_of_week": [0],
            },
        )
        monday_1500_tashkent = datetime(2026, 7, 20, 10, 0, tzinfo=timezone.utc)
        active = active_promotions_for_tenant(tenant, now_utc=monday_1500_tashkent)
        require("happy hours use tenant local time", len(active) == 1, active)


def scenario_days_of_week_validation() -> None:
    with isolated_app() as (client, _):
        create_tenant("promotion-days")
        response = client.post(
            "/t/promotion-days/api/admin/promotions",
            headers={"x-admin-token": ADMIN_SECRET},
            json={
                "type": "happy_hours",
                "is_active": True,
                "discount_percent": 10,
                "days_of_week": [7],
            },
        )
        require("out-of-range promotion day rejected", response.status_code == 422, response.text)
