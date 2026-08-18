from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace

from fastapi import BackgroundTasks, HTTPException, Request


BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))


def require(label: str, condition: bool, detail: object = "") -> None:
    if not condition:
        raise AssertionError(f"{label}: {detail}".rstrip())


async def verify() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        os.environ["DATABASE_URL"] = f"sqlite:///{(Path(tmp) / 'background.db').as_posix()}"
        os.environ["ADMIN_SECRET"] = "telegram_background_regression_secret"

        import src.api_app as api_app
        import src.notifier as notifier

        logged: list[str] = []
        original_logger_exception = notifier.logger.exception
        notifier.logger.exception = lambda message, *args, **kwargs: logged.append(message)
        try:
            async def failing_notification():
                raise RuntimeError("forced notification failure")

            await notifier.best_effort_notify(failing_notification, event="regression")
        finally:
            notifier.logger.exception = original_logger_exception
        require(
            "best_effort_notify logs unexpected exception",
            logged == [
                "notification_unexpected_failed event=%s tenant_id=%s tenant=%s order_id=%s reservation_id=%s exception_type=%s"
            ],
            logged,
        )

        original_add_order = api_app.add_order
        original_notify_admin = api_app.notify_admin
        notify_calls: list[int] = []

        def failing_add_order(*args, **kwargs):
            raise ValueError("forced database write failure")

        async def tracking_notify(order_id: int, tenant_id: int):
            notify_calls.append(order_id)

        api_app.add_order = failing_add_order
        api_app.notify_admin = tracking_notify
        background_tasks = BackgroundTasks()
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/t/demo/orders",
                "headers": [],
                "client": ("198.51.100.40", 12345),
                "app": api_app.app,
            }
        )
        order = api_app.OrderIn.model_validate(
            {
                "items": [{"item_id": "1", "qty": 1}],
                "customer": {"name": "Failure", "phone": "P", "address": "A"},
            }
        )
        try:
            try:
                await api_app.create_order_by_slug(
                    "demo",
                    order,
                    request,
                    background_tasks,
                    x_internal_token=None,
                    tenant=SimpleNamespace(id=1),
                )
            except HTTPException as exc:
                require("database failure remains HTTP 400", exc.status_code == 400, exc.status_code)
            else:
                raise AssertionError("database write failure did not fail request")
        finally:
            api_app.add_order = original_add_order
            api_app.notify_admin = original_notify_admin
        require("database failure schedules no notification", not background_tasks.tasks, len(background_tasks.tasks))
        require("database failure calls no notifier", not notify_calls, notify_calls)

        async def background_failure():
            raise RuntimeError("forced background failure")

        response_tasks = BackgroundTasks()
        response_tasks.add_task(notifier.best_effort_notify, background_failure, event="after_response")
        response = {"ok": True}
        await response_tasks()
        require("background exception does not alter HTTP result", response == {"ok": True}, response)


def main() -> None:
    finding = "Telegram best-effort background semantics"
    try:
        asyncio.run(verify())
    except Exception as exc:
        print(json.dumps({"status": "failed", "finding": finding, "error": f"{type(exc).__name__}: {exc}"}, indent=2))
        raise SystemExit(1)
    print(json.dumps({"status": "ok", "finding": finding, "issues": []}, indent=2))


if __name__ == "__main__":
    main()
