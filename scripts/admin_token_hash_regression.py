from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from sqlalchemy import select


BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))


def require(label: str, condition: bool, detail: object = "") -> None:
    if not condition:
        raise AssertionError(f"{label}: {detail}".rstrip())


def run_alembic(database_url: str, *args: str) -> None:
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BASE_DIR,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
    )
    require(f"alembic {' '.join(args)}", result.returncode == 0, result.stderr or result.stdout)


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def main() -> None:
    finding = "admin bearer tokens hashed at rest"
    try:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            database_url = f"sqlite:///{(Path(tmp) / 'auth-hash.db').as_posix()}"
            run_alembic(database_url, "upgrade", "0015_tenant_timezone")
            os.environ["DATABASE_URL"] = database_url
            os.environ["ADMIN_SECRET"] = "admin_token_hash_regression_secret"

            from src.db import engine, get_session
            from src.db_models import AdminLoginToken, AdminSession, Tenant

            now = datetime.utcnow()
            legacy_login_token = "legacy-login-token"
            legacy_session_token = "legacy-session-token"
            with get_session() as session:
                tenant = Tenant(
                    slug="auth-hash",
                    name="Auth Hash",
                    admin_chat_id=1,
                    bot_enabled=False,
                    timezone="Asia/Tashkent",
                    features={},
                    is_active=True,
                )
                session.add(tenant)
                session.flush()
                tenant_id = int(tenant.id)
                session.add_all(
                    [
                        AdminLoginToken(
                            tenant_id=tenant_id,
                            token=legacy_login_token,
                            used=False,
                            expires_at=now + timedelta(minutes=10),
                        ),
                        AdminSession(
                            tenant_id=tenant_id,
                            session_token=legacy_session_token,
                            expires_at=now + timedelta(days=1),
                        ),
                    ]
                )
            engine.dispose()

            run_alembic(database_url, "upgrade", "head")
            with get_session() as session:
                migrated_login = session.execute(select(AdminLoginToken)).scalar_one()
                migrated_session = session.execute(select(AdminSession)).scalar_one()
                require("legacy login token hashed", migrated_login.token == token_hash(legacy_login_token))
                require(
                    "legacy admin session hashed",
                    migrated_session.session_token == token_hash(legacy_session_token),
                )

            from src.store import (
                consume_admin_login_token_for_slug,
                create_admin_login_token_for_tenant,
                create_admin_session,
                get_admin_session,
                get_tenant_by_slug,
                revoke_admin_session,
            )

            tenant = get_tenant_by_slug("auth-hash")
            issued_login = create_admin_login_token_for_tenant(tenant)
            with get_session() as session:
                stored_login = session.execute(
                    select(AdminLoginToken).where(
                        AdminLoginToken.token == token_hash(issued_login.token)
                    )
                ).scalar_one()
                require("raw login token absent from DB", stored_login.token != issued_login.token)
            require(
                "hashed login token remains consumable",
                consume_admin_login_token_for_slug(issued_login.token, tenant.slug) == tenant.id,
            )

            issued_session = create_admin_session(tenant.id)
            with get_session() as session:
                stored_session = session.execute(
                    select(AdminSession).where(
                        AdminSession.session_token == token_hash(issued_session.session_token)
                    )
                ).scalar_one()
                require("raw admin session absent from DB", stored_session.session_token != issued_session.session_token)
            engine.dispose()
            require("hashed session survives engine restart", get_admin_session(issued_session.session_token) is not None)
            engine.dispose()
            run_alembic(database_url, "downgrade", "0015_tenant_timezone")
            run_alembic(database_url, "upgrade", "head")
            require(
                "hashed session survives migration roundtrip",
                get_admin_session(issued_session.session_token) is not None,
            )
            require("hashed session revoke succeeds", revoke_admin_session(issued_session.session_token))
            require("revoked session rejected", get_admin_session(issued_session.session_token) is None)
            engine.dispose()
    except Exception as exc:
        print(json.dumps({"status": "failed", "finding": finding, "error": f"{type(exc).__name__}: {exc}"}, indent=2))
        raise SystemExit(1)
    print(json.dumps({"status": "ok", "finding": finding, "issues": []}, indent=2))


if __name__ == "__main__":
    main()
