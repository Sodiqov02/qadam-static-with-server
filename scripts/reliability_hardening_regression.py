from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

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

    async def bot_manager_reconciles_runtime_changes() -> None:
        import src.bot_manager as bot_manager_module

        manager = bot_manager_module.BotManager()
        started: list[tuple] = []
        stopped: list[tuple] = []

        async def fake_run_bot(tenant):
            fingerprint = manager._runtime_fingerprint(tenant)
            started.append(fingerprint)
            try:
                await asyncio.Event().wait()
            finally:
                stopped.append(fingerprint)

        manager._run_bot = fake_run_bot
        tenant = SimpleNamespace(
            id=1,
            bot_token="12345:test-token",
            slug="demo",
            name="Demo",
            admin_chat_id=1,
            features={"plan": "standard"},
            description="first",
        )
        await manager._reconcile([tenant])
        first_task = manager._tasks[1]
        await asyncio.sleep(0)
        await manager._reconcile([tenant])
        expect("unchanged tenant task reused", manager._tasks[1] is first_task)

        tenant.description = "irrelevant change"
        await manager._reconcile([tenant])
        expect("irrelevant tenant field does not restart bot", manager._tasks[1] is first_task)

        tenant.admin_chat_id = 2
        await manager._reconcile([tenant])
        await asyncio.sleep(0)
        expect("runtime tenant field restarts one bot", manager._tasks[1] is not first_task)
        expect("old bot task awaited during restart", len(stopped) == 1, str(stopped))

        await manager._reconcile([])
        expect("removed tenant task stopped", not manager._tasks)
        expect("removed tenant task awaited", len(stopped) == 2, str(stopped))

    asyncio.run(bot_manager_reconciles_runtime_changes())

    async def notifier_cache_closes_replaced_and_shutdown_sessions() -> None:
        import src.notifier as notifier

        class FakeSession:
            def __init__(self):
                self.close_calls = 0

            async def close(self):
                self.close_calls += 1

        class FakeBot:
            def __init__(self, token, default=None):
                self.token = token
                self.session = FakeSession()

        original_bot = notifier.Bot
        notifier.Bot = FakeBot
        notifier._bot_cache.clear()
        notifier._tenant_tokens.clear()
        try:
            tenant = SimpleNamespace(id=1, bot_token="12345:first", bot_enabled=True)
            first = await notifier._get_bot_for_tenant(tenant)
            reused = await notifier._get_bot_for_tenant(tenant)
            expect("same notifier bot token reused", reused is first)

            tenant.bot_token = "12345:second"
            second = await notifier._get_bot_for_tenant(tenant)
            expect("changed notifier token creates new bot", second is not first)
            expect("old notifier bot session closed", first.session.close_calls == 1)
            expect("old notifier cache entry removed", "12345:first" not in notifier._bot_cache)

            shared_tenant = SimpleNamespace(id=2, bot_token="12345:second", bot_enabled=True)
            shared = await notifier._get_bot_for_tenant(shared_tenant)
            expect("shared notifier token reuses bot", shared is second)
            tenant.bot_enabled = False
            disabled = await notifier._get_bot_for_tenant(tenant)
            expect("disabled tenant has no notifier bot", disabled is None)
            expect("disabled tenant cache mapping removed", 1 not in notifier._tenant_tokens)
            expect("shared notifier bot remains open", second.session.close_calls == 0)

            await notifier.release_tenant_bot(shared_tenant.id)
            expect("deleted tenant cache mapping removed", 2 not in notifier._tenant_tokens)
            expect("last tenant release closes notifier bot", second.session.close_calls == 1)
            expect("released notifier bot removed from cache", "12345:second" not in notifier._bot_cache)

            active_tenant = SimpleNamespace(id=3, bot_token="12345:active", bot_enabled=True)
            active = await notifier._get_bot_for_tenant(active_tenant)
            await notifier.close_bot_cache()
            expect("notifier shutdown closes active bot", active.session.close_calls == 1)
            expect("notifier shutdown clears cache", not notifier._bot_cache and not notifier._tenant_tokens)

            class FailingSession(FakeSession):
                async def close(self):
                    self.close_calls += 1
                    raise RuntimeError("forced close failure")

            first_failing = FakeBot("12345:failing")
            first_failing.session = FailingSession()
            remaining = FakeBot("12345:remaining")
            notifier._bot_cache.update(
                {
                    first_failing.token: first_failing,
                    remaining.token: remaining,
                }
            )
            notifier._tenant_tokens.update({1: first_failing.token, 2: remaining.token})
            records: list[logging.LogRecord] = []

            class Capture(logging.Handler):
                def emit(self, record):
                    records.append(record)

            handler = Capture()
            notifier.logger.addHandler(handler)
            try:
                await notifier.close_bot_cache()
            finally:
                notifier.logger.removeHandler(handler)
            expect("failing notifier session close attempted", first_failing.session.close_calls == 1)
            expect("remaining notifier session still closed", remaining.session.close_calls == 1)
            expect("failed notifier close still clears cache", not notifier._bot_cache and not notifier._tenant_tokens)
            expect(
                "failed notifier close logged",
                any(record.getMessage().startswith("bot_cache_close_failed") for record in records),
            )
        finally:
            notifier.Bot = original_bot
            await notifier.close_bot_cache()

    asyncio.run(notifier_cache_closes_replaced_and_shutdown_sessions())

    print(json.dumps({"status": "ok" if not issues else "failed", "issues": issues}, indent=2))
    if issues:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
