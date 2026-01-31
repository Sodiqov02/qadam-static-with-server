import argparse
from datetime import datetime, timedelta
from decimal import Decimal

from src.db import get_session
from src.db_models import Order
from src.store import DEFAULT_TENANT_SLUG, _price_lookup, ensure_default_tenant, get_tenant_by_slug


def main():
    parser = argparse.ArgumentParser(description="Seed demo orders for analytics")
    parser.add_argument("--slug", default=DEFAULT_TENANT_SLUG, help="Tenant slug")
    parser.add_argument("--days", type=int, default=14, help="How many past days to seed")
    parser.add_argument("--orders-per-day", type=int, default=2, help="Orders per day")
    args = parser.parse_args()

    tenant = get_tenant_by_slug(args.slug) or ensure_default_tenant()
    price_map = _price_lookup(tenant)
    if not price_map:
        print("No menu items found; seed menu first.")
        return
    item_ids = list(price_map.keys())

    created = 0
    with get_session() as session:
        for day in range(args.days):
            created_at = datetime.utcnow() - timedelta(days=day)
            for idx in range(args.orders_per_day):
                item_id = item_ids[(day + idx) % len(item_ids)]
                qty = (idx % 3) + 1
                price = Decimal(price_map[item_id].get("price") or 0)
                total = (price * qty).quantize(Decimal("0.01"))
                status = "COMPLETED" if (day + idx) % 3 == 0 else "NEW"
                order = Order(
                    tenant_id=tenant.id,
                    source="seed",
                    status=status,
                    items=[{"item_id": item_id, "qty": qty}],
                    total=total,
                    created_at=created_at,
                    customer_name="Seed Customer",
                    customer_phone="+100000000",
                    customer_address="Seed Address",
                    raw_payload={"seed": True},
                )
                session.add(order)
                created += 1
    print(f"Seeded {created} orders for tenant {tenant.slug}")


if __name__ == "__main__":
    main()
