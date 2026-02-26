import argparse
import json
from typing import Any, Dict

from src.store import bootstrap_tenant


def _parse_features(flags: list[str], plan: str) -> Dict[str, Any]:
    features: Dict[str, Any] = {}
    for flag in flags:
        key = (flag or "").strip()
        if key:
            features[key] = True
    features["plan"] = (plan or "basic").strip().lower()
    return features


def main() -> None:
    parser = argparse.ArgumentParser(description="Provision or update one tenant for production use")
    parser.add_argument("--slug", required=True, help="Tenant slug (unique)")
    parser.add_argument("--name", required=True, help="Tenant display name")
    parser.add_argument("--admin-chat-id", type=int, required=True, help="Tenant admin Telegram chat id")
    parser.add_argument("--bot-token", help="Tenant Telegram bot token")
    parser.add_argument("--bot-username", help="Tenant Telegram bot username without @")
    parser.add_argument("--enable-bot", action="store_true", help="Enable tenant bot polling")
    parser.add_argument("--plan", default="basic", help="Plan: basic | standard | vip")
    parser.add_argument("--feature", action="append", default=[], help="Feature flag (repeatable)")
    parser.add_argument(
        "--category",
        action="append",
        default=[],
        help="Initial empty category title (repeatable). Defaults to 'Main'",
    )
    args = parser.parse_args()

    result = bootstrap_tenant(
        slug=args.slug.strip(),
        name=args.name.strip(),
        admin_chat_id=args.admin_chat_id,
        bot_token=(args.bot_token or "").strip() or None,
        bot_username=(args.bot_username or "").strip() or None,
        bot_enabled=bool(args.enable_bot),
        features=_parse_features(args.feature, args.plan),
        category_titles=args.category,
    )
    action = "created" if result["created"] else "updated"
    print(
        json.dumps(
            {
                "status": "ok",
                "action": action,
                "tenant_id": result["tenant_id"],
                "slug": result["slug"],
                "categories_created": result["categories_created"],
            },
            ensure_ascii=True,
        )
    )


if __name__ == "__main__":
    main()
