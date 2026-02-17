import argparse
import asyncio
import json
from pathlib import Path

import httpx

from src.db import get_session
from src.db_models import Tenant
from src.store import import_menu_json, list_enabled_bot_tenants, set_status

DATA_MENU = Path(__file__).resolve().parents[1] / "data" / "menu.json"


def ensure_tenant(slug: str, *, admin_chat_id: int | None = None, bot_token: str | None = None) -> Tenant:
    with get_session() as session:
        tenant = session.query(Tenant).filter(Tenant.slug == slug).one_or_none()
        if tenant:
            tenant.features = {"reservations": True, "plan": "standard"}
            tenant.bot_enabled = True
            tenant.bot_token = bot_token
            tenant.admin_chat_id = admin_chat_id
            session.flush()
            return tenant
        tenant = Tenant(
            slug=slug,
            name=f"{slug} tenant",
            admin_chat_id=admin_chat_id,
            bot_enabled=True,
            bot_token=bot_token,
            features={"reservations": True, "plan": "standard"},
        )
        session.add(tenant)
        session.flush()
        return tenant


async def create_order(client: httpx.AsyncClient, base: str, slug: str, phone: str, item_id: str) -> int:
    payload = {
        "items": [{"item_id": item_id, "qty": 1}],
        "customer": {"name": slug, "phone": phone, "address": "Smoke street", "comment": "-"},
        "source": "site",
    }
    r = await client.post(f"{base}/t/{slug}/orders", json=payload, timeout=10)
    r.raise_for_status()
    return int(r.json()["order_id"])


async def main():
    parser = argparse.ArgumentParser(description="Smoke test: multi-tenant isolation")
    parser.add_argument("--base-url", default="http://localhost:8000", help="API base url")
    parser.add_argument("--slug-a", default="smoke-a", help="First tenant slug")
    parser.add_argument("--slug-b", default="smoke-b", help="Second tenant slug")
    args = parser.parse_args()

    tenant_a = ensure_tenant(args.slug_a, admin_chat_id=10001, bot_token=f"token-{args.slug_a}")
    tenant_b = ensure_tenant(args.slug_b, admin_chat_id=10002, bot_token=f"token-{args.slug_b}")

    if DATA_MENU.exists():
        menu_data = json.loads(DATA_MENU.read_text(encoding="utf-8"))
        import_menu_json(tenant_a, menu_data)
        import_menu_json(tenant_b, menu_data)
        print(f"Imported menu for tenants {tenant_a.slug}, {tenant_b.slug}")

    enabled = list_enabled_bot_tenants()
    enabled_tokens = [t.bot_token for t in enabled if t.slug in {tenant_a.slug, tenant_b.slug}]
    assert len(set(enabled_tokens)) == 2, "Bot tokens must be unique per tenant"
    print("Bot tenants enabled with unique tokens")

    base = args.base_url.rstrip("/")
    async with httpx.AsyncClient() as client:
        menu_a = await client.get(f"{base}/t/{tenant_a.slug}/menu", timeout=10)
        menu_b = await client.get(f"{base}/t/{tenant_b.slug}/menu", timeout=10)
        menu_a.raise_for_status()
        menu_b.raise_for_status()
        item_a = menu_a.json()["categories"][0]["items"][0]["id"]
        item_b = menu_b.json()["categories"][0]["items"][0]["id"]

        order_a = await create_order(client, base, tenant_a.slug, "+998900000001", item_a)
        order_b = await create_order(client, base, tenant_b.slug, "+998900000002", item_b)
        print(f"Orders created: tenantA=#{order_a}, tenantB=#{order_b}")

        hist_a = await client.get(
            f"{base}/t/{tenant_a.slug}/api/orders/history",
            params={"phone": "+998900000001"},
            timeout=10,
        )
        hist_b = await client.get(
            f"{base}/t/{tenant_b.slug}/api/orders/history",
            params={"phone": "+998900000002"},
            timeout=10,
        )
        hist_a.raise_for_status()
        hist_b.raise_for_status()

        ids_a = {x["id"] for x in hist_a.json().get("items", [])}
        ids_b = {x["id"] for x in hist_b.json().get("items", [])}
        assert order_a in ids_a and order_b in ids_b, "Own orders must be visible"
        assert order_b not in ids_a and order_a not in ids_b, "Orders leaked across tenants"
        print("Order isolation check passed")

    ok = set_status(order_a, "ACCEPTED", admin_chat_id=tenant_a.admin_chat_id)
    print(f"Status update tenantA accepted: {ok}")
    ok = set_status(order_a, "COOKING", admin_chat_id=tenant_a.admin_chat_id)
    print(f"Status update tenantA cooking: {ok}")
    ok = set_status(order_a, "READY", admin_chat_id=tenant_a.admin_chat_id)
    print(f"Status update tenantA ready: {ok}")
    ok = set_status(order_a, "COMPLETED", admin_chat_id=tenant_a.admin_chat_id)
    print(f"Status update tenantA completed: {ok}")
    print("Multi-tenant smoke test finished.")


if __name__ == "__main__":
    asyncio.run(main())
