import argparse
import json
from typing import Dict, Any

from src.db import get_session
from src.db_models import Tenant


def parse_features(features: list[str]) -> Dict[str, Any]:
    parsed: Dict[str, Any] = {}
    for feat in features:
        parsed[feat] = True
    return parsed


def main():
    parser = argparse.ArgumentParser(description="Create tenant quickly")
    parser.add_argument("--slug", required=True, help="Tenant slug (unique)")
    parser.add_argument("--name", required=True, help="Tenant name")
    parser.add_argument("--admin_chat_id", type=int, help="Telegram admin chat id")
    parser.add_argument("--features", nargs="*", default=[], help="Feature flags, e.g. reservations")
    args = parser.parse_args()

    features = parse_features(args.features)

    with get_session() as session:
        existing = session.query(Tenant).filter(Tenant.slug == args.slug).one_or_none()
        if existing:
            print(f"Tenant {args.slug} already exists (id={existing.id})")
            return
        tenant = Tenant(
            slug=args.slug,
            name=args.name,
            admin_chat_id=args.admin_chat_id,
            features=features,
            is_active=True,
        )
        session.add(tenant)
        session.flush()
        print(f"Created tenant {args.slug} (id={tenant.id}) with features={json.dumps(features)}")


if __name__ == "__main__":
    main()
