import argparse
import json
from pathlib import Path
from typing import Any, Dict

from src.db import get_session
from src.db_models import Tenant
from src.store import import_menu_json

DEFAULT_MENU = Path(__file__).resolve().parents[1] / "data" / "menu_test_tenant.json"


def parse_features(features: list[str]) -> Dict[str, Any]:
    parsed: Dict[str, Any] = {}
    for feat in features:
        parsed[feat] = True
    return parsed


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed a demo tenant with a distinct menu")
    parser.add_argument("--slug", default="test-tenant", help="Tenant slug (unique)")
    parser.add_argument("--name", default="Test tenant", help="Tenant name")
    parser.add_argument("--admin_chat_id", type=int, help="Telegram admin chat id")
    parser.add_argument("--features", nargs="*", default=[], help="Feature flags, e.g. reservations")
    parser.add_argument("--menu_path", default=str(DEFAULT_MENU), help="Path to menu JSON")
    args = parser.parse_args()

    menu_path = Path(args.menu_path)
    if not menu_path.exists():
        raise SystemExit(f"Menu file not found: {menu_path}")
    menu_data = json.loads(menu_path.read_text(encoding="utf-8"))
    features = parse_features(args.features)

    with get_session() as session:
        tenant = session.query(Tenant).filter(Tenant.slug == args.slug).one_or_none()
        if tenant:
            tenant.name = args.name or tenant.name
            if args.admin_chat_id is not None:
                tenant.admin_chat_id = args.admin_chat_id
            if features:
                tenant.features = features
            tenant.is_active = True
        else:
            tenant = Tenant(
                slug=args.slug,
                name=args.name,
                admin_chat_id=args.admin_chat_id,
                features=features,
                is_active=True,
            )
            session.add(tenant)
            session.flush()
        tenant_id = tenant.id
    import_menu_json(tenant, menu_data)
    print(f"Seeded tenant {args.slug} (id={tenant_id}) with menu {menu_path}")


if __name__ == "__main__":
    main()
