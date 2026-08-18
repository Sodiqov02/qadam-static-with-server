from __future__ import annotations

import concurrent.futures
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import sys
import tempfile
import threading

from sqlalchemy.exc import SQLAlchemyError


BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))


def require(label: str, condition: bool, detail: object = "") -> None:
    if not condition:
        raise AssertionError(f"{label}: {detail}".rstrip())


def main() -> None:
    finding = "auth cleanup cadence"
    try:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            os.environ["DATABASE_URL"] = f"sqlite:///{(Path(tmp) / 'auth.db').as_posix()}"
            os.environ["ADMIN_SECRET"] = "auth_cleanup_regression_secret"
            os.environ["API_BASE_URL"] = "http://127.0.0.1:8000"

            from fastapi.testclient import TestClient
            import src.api_app as api_app
            from src.db import engine, get_session
            from src.db_models import AdminSession
            from src.store import bootstrap_tenant, cleanup_expired_auth_records, get_tenant_by_slug

            calls: list[str] = []
            original_cleanup = api_app.cleanup_expired_auth_records
            original_throttle = api_app.auth_cleanup_throttle

            def fake_cleanup():
                calls.append("cleanup")
                return {"admin_sessions": 0, "operator_sessions": 0, "login_tokens": 0}

            api_app.cleanup_expired_auth_records = fake_cleanup
            api_app.auth_cleanup_throttle = api_app.AuthCleanupThrottle(interval_seconds=3600)
            try:
                with TestClient(api_app.app) as client:
                    require("startup cleanup remains", calls == ["cleanup"], calls)

                    login = client.post(
                        "/api/onboarding/operator-login",
                        json={"secret": "auth_cleanup_regression_secret"},
                    )
                    require("auth request succeeds", login.status_code == 200, login.text)
                    require("startup defer prevents immediate repeat", calls == ["cleanup"], calls)

                    api_app.auth_cleanup_throttle._next_run = 0
                    repeat = client.post(
                        "/api/onboarding/operator-login",
                        json={"secret": "auth_cleanup_regression_secret"},
                    )
                    require("cleanup runs after interval", repeat.status_code == 200 and len(calls) == 2, calls)

                    client.post(
                        "/api/onboarding/operator-login",
                        json={"secret": "auth_cleanup_regression_secret"},
                    )
                    require("repeated auth request is throttled", len(calls) == 2, calls)

                    logged_failures: list[str] = []
                    original_logger_exception = api_app.logger.exception

                    def failing_cleanup():
                        raise SQLAlchemyError("forced cleanup failure")

                    api_app.cleanup_expired_auth_records = failing_cleanup
                    api_app.logger.exception = lambda message, *args, **kwargs: logged_failures.append(message)
                    api_app.auth_cleanup_throttle._next_run = 0
                    try:
                        after_failure = client.post(
                            "/api/onboarding/operator-login",
                            json={"secret": "auth_cleanup_regression_secret"},
                        )
                    finally:
                        api_app.cleanup_expired_auth_records = fake_cleanup
                        api_app.logger.exception = original_logger_exception
                    require("cleanup failure does not break auth request", after_failure.status_code == 200, after_failure.text)
                    require("cleanup failure is logged", logged_failures == ["auth_cleanup_failed"], logged_failures)
            finally:
                api_app.cleanup_expired_auth_records = original_cleanup
                api_app.auth_cleanup_throttle = original_throttle

            throttle = api_app.AuthCleanupThrottle(interval_seconds=10)
            direct_calls: list[float] = []
            require("first due cleanup runs", throttle.maybe_cleanup(lambda: direct_calls.append(1) or {}, now=100))
            require("request inside interval skips", not throttle.maybe_cleanup(lambda: direct_calls.append(2) or {}, now=105))
            require("request after interval runs", throttle.maybe_cleanup(lambda: direct_calls.append(3) or {}, now=110))
            require("cadence call count", direct_calls == [1, 3], direct_calls)

            concurrent_throttle = api_app.AuthCleanupThrottle(interval_seconds=10)
            entered = threading.Event()
            release = threading.Event()
            concurrent_calls = 0
            concurrent_lock = threading.Lock()

            def blocking_cleanup():
                nonlocal concurrent_calls
                with concurrent_lock:
                    concurrent_calls += 1
                entered.set()
                release.wait(timeout=5)
                return {}

            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                first = pool.submit(concurrent_throttle.maybe_cleanup, blocking_cleanup, 200)
                require("concurrent cleanup entered", entered.wait(timeout=5))
                others = [
                    pool.submit(concurrent_throttle.maybe_cleanup, blocking_cleanup, 200)
                    for _ in range(7)
                ]
                release.set()
                results = [first.result(timeout=5), *(item.result(timeout=5) for item in others)]
            require("only one concurrent cleanup runs", concurrent_calls == 1 and results.count(True) == 1, results)

            logged_failures: list[str] = []
            original_logger_exception = api_app.logger.exception
            api_app.logger.exception = lambda message, *args, **kwargs: logged_failures.append(message)
            try:
                failure_throttle = api_app.AuthCleanupThrottle(interval_seconds=10)

                def failing_cleanup():
                    raise SQLAlchemyError("forced cleanup failure")

                require("cleanup failure is contained", failure_throttle.maybe_cleanup(failing_cleanup, now=300))
                require(
                    "cleanup failure is logged",
                    logged_failures == ["auth_cleanup_failed"],
                )
            finally:
                api_app.logger.exception = original_logger_exception

            bootstrap_tenant(
                slug="auth-cleanup",
                name="Auth Cleanup",
                admin_chat_id=1,
                bot_token=None,
                bot_username=None,
                bot_enabled=False,
                features={"plan": "standard"},
                category_titles=["Main"],
            )
            tenant = get_tenant_by_slug("auth-cleanup")
            now = datetime.utcnow()
            with get_session() as session:
                session.add_all(
                    [
                        AdminSession(
                            tenant_id=tenant.id,
                            session_token="active-session",
                            created_at=now,
                            expires_at=now + timedelta(hours=1),
                        ),
                        AdminSession(
                            tenant_id=tenant.id,
                            session_token="expired-session",
                            created_at=now - timedelta(days=2),
                            expires_at=now - timedelta(seconds=1),
                        ),
                    ]
                )
            cleanup_expired_auth_records(now)
            with get_session() as session:
                active = session.query(AdminSession).filter_by(session_token="active-session").one_or_none()
                expired = session.query(AdminSession).filter_by(session_token="expired-session").one_or_none()
            require("active session preserved", active is not None)
            require("expired session removed", expired is None)
            engine.dispose()
    except Exception as exc:
        print(json.dumps({"status": "failed", "finding": finding, "error": f"{type(exc).__name__}: {exc}"}, indent=2))
        raise SystemExit(1)
    print(json.dumps({"status": "ok", "finding": finding, "issues": []}, indent=2))


if __name__ == "__main__":
    main()
