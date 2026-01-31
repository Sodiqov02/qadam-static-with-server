import argparse
import asyncio
import json
from pathlib import Path

import httpx

from src.db import get_session
from src.db_models import Tenant
from src.store import import_menu_json, set_status

DATA_MENU = Path(__file__).resolve().parents[1] / "data" / "menu.json"


def ensure_tenant(slug: str, admin_chat_id: int | None = None) -> Tenant:
    with get_session() as session:
        tenant = session.query(Tenant).filter(Tenant.slug == slug).one_or_none()
        if tenant:
            return tenant
        tenant = Tenant(
            slug=slug,
            name=f"{slug} tenant",
            admin_chat_id=admin_chat_id,
            features={"reservations": True, "plan": "standard"},
        )
        session.add(tenant)
        session.flush()
        return tenant


async def main():
    parser = argparse.ArgumentParser(description="Smoke test: tenant -> menu -> order -> status")
    parser.add_argument("--base-url", default="http://localhost:8000", help="API base url")
    parser.add_argument("--slug", default="smoke", help="Tenant slug for the test")
    args = parser.parse_args()

    tenant = ensure_tenant(args.slug)
    if DATA_MENU.exists():
        import_menu_json(tenant, json.loads(DATA_MENU.read_text(encoding="utf-8")))
        print(f"Imported menu for tenant {tenant.slug}")

    base = args.base_url.rstrip("/")
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{base}/t/{args.slug}/menu", timeout=10)
        r.raise_for_status()
        print("Menu ok")

        order_payload = {
            "items": [{"item_id": r.json()["categories"][0]["items"][0]["id"], "qty": 1}],
            "customer": {"name": "Smoke Test", "phone": "+998900000000", "address": "Test street", "comment": "-"},
            "source": "site",
        }
        r2 = await client.post(f"{base}/t/{args.slug}/orders", json=order_payload, timeout=10)
        r2.raise_for_status()
        order = r2.json()
        print(f"Order created #{order['order_id']}")

    ok = set_status(order["order_id"], "ACCEPTED")
    print(f"Status update accepted: {ok}")
    ok = set_status(order["order_id"], "COOKING")
    print(f"Status update cooking: {ok}")
    ok = set_status(order["order_id"], "READY")
    print(f"Status update ready: {ok}")
    ok = set_status(order["order_id"], "COMPLETED")
    print(f"Status update completed: {ok}")
    print("Smoke test finished.")


if __name__ == "__main__":
    asyncio.run(main())
