from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

from sqlalchemy import select, text
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
        db_path = Path(tmp) / "reliability.db"
        os.environ["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
        os.environ["ADMIN_SECRET"] = "reliability_regression_secret"
        os.environ["UPLOADS_DIR"] = str(Path(tmp) / "uploads")
        os.environ["MENU_IMAGES_DIR"] = str(Path(tmp) / "menu_images")

        from src.db import engine, get_session
        from src.db_models import Base, Tenant

        try:
            Base.metadata.create_all(engine)
            with engine.connect() as connection:
                expect("journal_mode wal", connection.execute(text("PRAGMA journal_mode")).scalar_one() == "wal")
                expect("foreign_keys on", int(connection.execute(text("PRAGMA foreign_keys")).scalar_one()) == 1)
                expect("busy_timeout set", int(connection.execute(text("PRAGMA busy_timeout")).scalar_one()) >= 10000)

            try:
                with get_session() as session:
                    session.add(
                        Tenant(
                            slug="rollback-check",
                            name="Rollback Check",
                            admin_chat_id=None,
                            bot_enabled=False,
                            features={},
                            is_active=True,
                        )
                    )
                    raise RuntimeError("force rollback")
            except RuntimeError:
                pass

            with get_session() as session:
                tenant = session.execute(select(Tenant).where(Tenant.slug == "rollback-check")).scalar_one_or_none()
            expect("transaction rollback removes partial tenant", tenant is None)
        finally:
            engine.dispose()

    async def bot_manager_survives_first_db_failure() -> None:
        import src.bot_manager as bot_manager_module

        manager = bot_manager_module.BotManager()
        calls = {"list": 0}
        delays: list[float] = []
        original_list = bot_manager_module.list_enabled_bot_tenants
        original_sleep = bot_manager_module.asyncio.sleep

        def flaky_list_enabled_bot_tenants():
            calls["list"] += 1
            if calls["list"] == 1:
                raise SQLAlchemyError("temporary db failure")
            return []

        async def fake_sleep(delay: float):
            delays.append(delay)
            if delay == 30:
                raise asyncio.CancelledError()

        bot_manager_module.list_enabled_bot_tenants = flaky_list_enabled_bot_tenants
        bot_manager_module.asyncio.sleep = fake_sleep
        try:
            try:
                await manager.start()
            except asyncio.CancelledError:
                pass
        finally:
            bot_manager_module.list_enabled_bot_tenants = original_list
            bot_manager_module.asyncio.sleep = original_sleep

        expect("bot manager retried after db failure", calls["list"] >= 2, str(calls))
        expect("bot manager used bounded initial backoff", delays[:1] == [2], str(delays))
        expect("bot manager reached next successful cycle", 30 in delays, str(delays))

    asyncio.run(bot_manager_survives_first_db_failure())

    print(json.dumps({"status": "ok" if not issues else "failed", "issues": issues}, indent=2))
    if issues:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
