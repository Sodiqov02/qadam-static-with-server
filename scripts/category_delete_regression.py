from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select


BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))


def main() -> None:
    issues: list[str] = []

    def stop(message: str) -> None:
        issues.append(message)
        print(json.dumps({"status": "failed", "issues": issues}, indent=2))
        raise SystemExit(1)

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db_path = Path(tmp) / "category_delete_regression.db"
        os.environ["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
        os.environ["ADMIN_SECRET"] = "dev_only_admin_secret"
        os.environ["API_BASE_URL"] = "http://127.0.0.1:8000"
        os.environ["UPLOADS_DIR"] = str(Path(tmp) / "uploads")
        os.environ["MENU_IMAGES_DIR"] = str(Path(tmp) / "menu_images")

        from src.api_app import app
        from src.db import engine, get_session
        from src.db_models import MenuItem, Tenant
        from src.store import bootstrap_tenant

        headers = {"x-admin-token": "dev_only_admin_secret"}
        try:
            with TestClient(app) as client:
                bootstrap_tenant(
                    slug="demo",
                    name="Demo",
                    admin_chat_id=100000001,
                    bot_token=None,
                    bot_username=None,
                    bot_enabled=False,
                    features={"plan": "standard"},
                    category_titles=["Protected", "Deleted target"],
                )

                categories_response = client.get("/t/demo/categories", headers=headers)
                if categories_response.status_code != 200:
                    stop(f"category list returned {categories_response.status_code}")
                categories = categories_response.json()["items"]
                protected = next(item for item in categories if item["title"] == "Protected")
                target = next(item for item in categories if item["title"] == "Deleted target")

                active_item = client.post(
                    "/admin/api/menu/demo",
                    headers=headers,
                    json={"name": "Active dish", "price": 12000, "category_id": protected["id"]},
                )
                if active_item.status_code != 200:
                    stop(f"active item create returned {active_item.status_code}: {active_item.text}")

                blocked_delete = client.delete(f"/t/demo/categories/{protected['id']}", headers=headers)
                if blocked_delete.status_code != 400:
                    issues.append(f"active item should block category deletion, got {blocked_delete.status_code}")

                deleted_item = client.post(
                    "/admin/api/menu/demo",
                    headers=headers,
                    json={"name": "Soft deleted dish", "price": 9000, "category_id": target["id"]},
                )
                if deleted_item.status_code != 200:
                    stop(f"soft target item create returned {deleted_item.status_code}: {deleted_item.text}")

                deleted_item_id = deleted_item.json()["id"]
                soft_delete = client.delete(f"/admin/api/menu/demo/{deleted_item_id}", headers=headers)
                if soft_delete.status_code != 200:
                    issues.append(f"admin item delete returned {soft_delete.status_code}: {soft_delete.text}")

                allowed_delete = client.delete(f"/t/demo/categories/{target['id']}", headers=headers)
                if allowed_delete.status_code != 200:
                    issues.append(f"soft-deleted item should not block category deletion, got {allowed_delete.status_code}: {allowed_delete.text}")

                with get_session() as session:
                    tenant_id = session.execute(select(Tenant.id).where(Tenant.slug == "demo")).scalar_one()
                    active_left = (
                        session.execute(
                            select(MenuItem).where(MenuItem.tenant_id == tenant_id, MenuItem.title == "Active dish")
                        )
                        .scalars()
                        .first()
                    )
                    deleted_left = (
                        session.execute(
                            select(MenuItem).where(MenuItem.tenant_id == tenant_id, MenuItem.id == deleted_item_id)
                        )
                        .scalars()
                        .first()
                    )
                if active_left is None or not active_left.is_active:
                    issues.append("unrelated active item was removed or deactivated")
                if deleted_left is not None:
                    issues.append("inactive item in deleted category was not cleaned up")

                public_page = client.get("/t/demo")
                if public_page.status_code != 200:
                    issues.append(f"/t/demo returned {public_page.status_code}")
        finally:
            engine.dispose()

    print(json.dumps({"status": "ok" if not issues else "failed", "issues": issues}, indent=2))
    if issues:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
