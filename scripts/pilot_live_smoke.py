from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import secrets
import sys
from urllib.parse import parse_qs, urlparse

import httpx


BASE_DIR = Path(__file__).resolve().parents[1]
SAMPLE_IMAGE = BASE_DIR / "static" / "demo" / "menu" / "classic-burger.webp"


def require(label: str, condition: bool, detail: object = "") -> None:
    if not condition:
        raise AssertionError(f"{label}: {detail}".rstrip())


def require_status(label: str, response: httpx.Response, expected: int) -> httpx.Response:
    require(label, response.status_code == expected, f"status={response.status_code} body={response.text[:500]}")
    return response


def login_operator(client: httpx.Client, secret: str) -> None:
    require_status(
        "operator login",
        client.post("/api/onboarding/operator-login", json={"secret": secret}),
        200,
    )


def create_tenant(client: httpx.Client, slug: str, name: str, chat_id: int, *, bot_token: str | None = None) -> dict:
    response = require_status(
        f"create tenant {slug}",
        client.post(
            "/api/onboarding/tenants",
            json={
                "slug": slug,
                "name": name,
                "admin_chat_id": chat_id,
                "plan": "standard",
                "bot_token": bot_token,
                "enable_bot": bool(bot_token),
                "initial_categories": ["Main"],
                "timezone": "Asia/Tashkent",
            },
        ),
        200,
    )
    return response.json()


def admin_token(tenant_payload: dict) -> str:
    query = parse_qs(urlparse(tenant_payload["admin_dashboard_url"]).query)
    token = query.get("admin_token", [""])[0]
    require("admin token returned", bool(token))
    return token


def login_admin(client: httpx.Client, slug: str, token: str) -> None:
    require_status(
        f"admin login {slug}",
        client.post("/admin/auth/login", json={"slug": slug, "token": token}),
        200,
    )


def create_menu_item(client: httpx.Client, slug: str, name: str) -> dict:
    categories = require_status(
        f"categories {slug}", client.get(f"/t/{slug}/categories"), 200
    ).json()["items"]
    require(f"initial category {slug}", len(categories) == 1, categories)

    with SAMPLE_IMAGE.open("rb") as image:
        upload = require_status(
            f"image upload {slug}",
            client.post(
                f"/admin/upload-image/{slug}",
                files={"file": (SAMPLE_IMAGE.name, image, "image/webp")},
            ),
            200,
        ).json()

    return require_status(
        f"create menu item {slug}",
        client.post(
            f"/admin/api/menu/{slug}",
            json={
                "name": name,
                "price": 45000,
                "category_id": categories[0]["id"],
                "image_path": upload["image_path"],
                "description": f"Pilot item for {slug}",
                "is_available": True,
            },
        ),
        200,
    ).json()


def place_order(client: httpx.Client, slug: str, item_id: int) -> int:
    response = require_status(
        f"place order {slug}",
        client.post(
            f"/t/{slug}/orders",
            json={
                "items": [{"item_id": str(item_id), "qty": 2}],
                "customer": {
                    "name": "Pilot Customer",
                    "phone": "+998901234567",
                    "address": "Pilot address",
                    "comment": "live smoke",
                },
            },
        ),
        200,
    )
    return int(response.json()["order_id"])


def run_full(base_url: str, operator_secret: str, state_path: Path) -> dict:
    suffix = secrets.token_hex(4)
    alpha_slug = f"pilot-alpha-{suffix}"
    beta_slug = f"pilot-beta-{suffix}"

    with httpx.Client(base_url=base_url, timeout=45, follow_redirects=True) as operator:
        require_status("health", operator.get("/healthz"), 200)
        require_status("readiness", operator.get("/readyz"), 200)
        login_operator(operator, operator_secret)
        alpha_payload = create_tenant(operator, alpha_slug, "Pilot Alpha", 100000001)
        beta_payload = create_tenant(operator, beta_slug, "Pilot Beta", 100000002)

        alpha = httpx.Client(base_url=base_url, timeout=45, follow_redirects=True)
        beta = httpx.Client(base_url=base_url, timeout=45, follow_redirects=True)
        try:
            login_admin(alpha, alpha_slug, admin_token(alpha_payload))
            login_admin(beta, beta_slug, admin_token(beta_payload))
            alpha_item = create_menu_item(alpha, alpha_slug, "Alpha Burger")
            beta_item = create_menu_item(beta, beta_slug, "Beta Burger")

            alpha_menu = require_status("alpha public menu", alpha.get(f"/t/{alpha_slug}/menu"), 200).text
            beta_menu = require_status("beta public menu", beta.get(f"/t/{beta_slug}/menu"), 200).text
            require("alpha menu contains own item", "Alpha Burger" in alpha_menu and "Beta Burger" not in alpha_menu)
            require("beta menu contains own item", "Beta Burger" in beta_menu and "Alpha Burger" not in beta_menu)

            require_status("cross-tenant admin menu denied", alpha.get(f"/admin/api/menu/{beta_slug}"), 403)
            require_status("cross-tenant reservations denied", alpha.get(f"/t/{beta_slug}/reservations"), 403)

            order_id = place_order(alpha, alpha_slug, int(alpha_item["id"]))
            require_status(
                "order status transition",
                alpha.patch(f"/t/{alpha_slug}/api/admin/orders/{order_id}/status", json={"status": "ACCEPTED"}),
                200,
            )

            reservation_id = int(
                require_status(
                    "create reservation",
                    alpha.post(
                        f"/t/{alpha_slug}/reservations",
                        json={
                            "name": "Pilot Guest",
                            "phone": "+998909876543",
                            "datetime": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
                            "guests": 3,
                        },
                    ),
                    200,
                ).json()["reservation_id"]
            )
            require_status(
                "confirm reservation",
                alpha.patch(f"/t/{alpha_slug}/reservations/{reservation_id}", json={"status": "confirmed"}),
                200,
            )

            promotion_id = int(
                require_status(
                    "create promotion",
                    alpha.post(
                        f"/t/{alpha_slug}/api/admin/promotions",
                        json={
                            "type": "item_of_the_day",
                            "is_active": True,
                            "product_id": int(alpha_item["id"]),
                        },
                    ),
                    200,
                ).json()["id"]
            )
            require_status("analytics", alpha.get(f"/t/{alpha_slug}/api/admin/analytics?range=7d"), 200)

            require_status("beta logout", beta.post("/admin/auth/logout"), 200)
            require_status("beta session revoked", beta.get(f"/admin/api/menu/{beta_slug}"), 401)

            state = {
                "alpha_slug": alpha_slug,
                "beta_slug": beta_slug,
                "alpha_item_id": int(alpha_item["id"]),
                "beta_item_id": int(beta_item["id"]),
                "order_id": order_id,
                "reservation_id": reservation_id,
                "promotion_id": promotion_id,
                "admin_session": alpha.cookies.get("admin_session"),
                "operator_session": operator.cookies.get("operator_session"),
            }
            require("admin session cookie", bool(state["admin_session"]))
            require("operator session cookie", bool(state["operator_session"]))
            state_path.write_text(json.dumps(state), encoding="utf-8")
            return {key: value for key, value in state.items() if not key.endswith("session")}
        finally:
            alpha.close()
            beta.close()


def verify_after_restart(base_url: str, state_path: Path) -> dict:
    state = json.loads(state_path.read_text(encoding="utf-8"))
    alpha_slug = state["alpha_slug"]
    beta_slug = state["beta_slug"]
    with httpx.Client(base_url=base_url, timeout=45, follow_redirects=True) as client:
        client.cookies.set("admin_session", state["admin_session"])
        require_status("readiness after restart", client.get("/readyz"), 200)
        require_status("admin session persisted", client.get(f"/admin/api/menu/{alpha_slug}"), 200)
        require_status("tenant boundary persisted", client.get(f"/admin/api/menu/{beta_slug}"), 403)
        menu_text = require_status("menu persisted", client.get(f"/t/{alpha_slug}/menu"), 200).text
        require("menu item persisted", "Alpha Burger" in menu_text)
        reservations = require_status(
            "reservation persisted", client.get(f"/t/{alpha_slug}/reservations"), 200
        ).json()["items"]
        require(
            "confirmed reservation persisted",
            any(int(row["id"]) == int(state["reservation_id"]) and row["status"] == "confirmed" for row in reservations),
            reservations,
        )
        promotions = require_status(
            "promotion persisted", client.get(f"/t/{alpha_slug}/api/admin/promotions"), 200
        ).json()["items"]
        require("promotion id persisted", any(int(row["id"]) == int(state["promotion_id"]) for row in promotions))

    with httpx.Client(base_url=base_url, timeout=45) as operator:
        operator.cookies.set("operator_session", state["operator_session"])
        require_status(
            "operator session persisted",
            operator.get("/api/onboarding/slug-check", params={"slug": f"unused-{secrets.token_hex(3)}"}),
            200,
        )
    return {"alpha_slug": alpha_slug, "beta_slug": beta_slug, "restart_verified": True}


def run_notification_failure(base_url: str, operator_secret: str) -> dict:
    suffix = secrets.token_hex(4)
    slug = f"pilot-failure-{suffix}"
    fake_token = f"{100000000 + secrets.randbelow(899999999)}:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi"
    with httpx.Client(base_url=base_url, timeout=60, follow_redirects=True) as operator:
        login_operator(operator, operator_secret)
        payload = create_tenant(operator, slug, "Pilot Failure", 100000003, bot_token=fake_token)
        with httpx.Client(base_url=base_url, timeout=60, follow_redirects=True) as admin:
            login_admin(admin, slug, admin_token(payload))
            item = create_menu_item(admin, slug, "Failure Burger")
            order_id = place_order(admin, slug, int(item["id"]))
            menu = require_status("failure order still readable", admin.get(f"/admin/api/menu/{slug}"), 200)
            require("failure tenant menu intact", any(row["id"] == item["id"] for row in menu.json()["items"]))
    return {"slug": slug, "order_id": order_id, "http_survived_notification_failure": True}


def main() -> None:
    parser = argparse.ArgumentParser(description="Live pilot smoke against a running production-like stack")
    parser.add_argument("mode", choices=("run", "verify-restart", "failure"))
    parser.add_argument("--base-url", default="http://localhost")
    parser.add_argument("--operator-secret")
    parser.add_argument("--state", type=Path)
    args = parser.parse_args()

    try:
        if args.mode == "run":
            require("operator secret required", bool(args.operator_secret))
            require("state path required", args.state is not None)
            result = run_full(args.base_url.rstrip("/"), args.operator_secret, args.state)
        elif args.mode == "verify-restart":
            require("state path required", args.state is not None)
            result = verify_after_restart(args.base_url.rstrip("/"), args.state)
        else:
            require("operator secret required", bool(args.operator_secret))
            result = run_notification_failure(args.base_url.rstrip("/"), args.operator_secret)
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": f"{type(exc).__name__}: {exc}"}, indent=2))
        raise SystemExit(1)
    print(json.dumps({"status": "ok", **result}, indent=2))


if __name__ == "__main__":
    main()
