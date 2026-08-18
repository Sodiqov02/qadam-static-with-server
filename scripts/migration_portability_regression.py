from __future__ import annotations

import inspect
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.schema import CreateTable


BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))


def require(label: str, condition: bool, detail: object = "") -> None:
    if not condition:
        raise AssertionError(f"{label}: {detail}".rstrip())


def run_alembic(database_url: str, *args: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BASE_DIR,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
    )


def main() -> None:
    finding = "operator session migration portability"
    try:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            database_url = f"sqlite:///{(Path(tmp) / 'migration.db').as_posix()}"
            for args in (
                ("upgrade", "head"),
                ("downgrade", "0013_tenant_branding_fields"),
                ("upgrade", "head"),
                ("check",),
            ):
                result = run_alembic(database_url, *args)
                require(f"alembic {' '.join(args)}", result.returncode == 0, result.stderr or result.stdout)

        metadata = sa.MetaData()
        operator_sessions = sa.Table(
            "operator_sessions",
            metadata,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("token_hash", sa.String(length=64), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
        )
        tenant_timezone = sa.Table(
            "tenant_timezone_check",
            metadata,
            sa.Column("timezone", sa.String(length=64), nullable=False, server_default="Asia/Tashkent"),
        )
        sqlite_operator = str(CreateTable(operator_sessions).compile(dialect=sqlite.dialect()))
        postgres_operator = str(CreateTable(operator_sessions).compile(dialect=postgresql.dialect()))
        sqlite_timezone = str(CreateTable(tenant_timezone).compile(dialect=sqlite.dialect()))
        postgres_timezone = str(CreateTable(tenant_timezone).compile(dialect=postgresql.dialect()))
        require("SQLite timestamp default compiles", "DEFAULT CURRENT_TIMESTAMP" in sqlite_operator, sqlite_operator)
        require("PostgreSQL timestamp default compiles", "DEFAULT now()" in postgres_operator, postgres_operator)
        require("SQLite timezone default is literal", "DEFAULT 'Asia/Tashkent'" in sqlite_timezone, sqlite_timezone)
        require("PostgreSQL timezone default is literal", "DEFAULT 'Asia/Tashkent'" in postgres_timezone, postgres_timezone)

        reconcile_source = (
            BASE_DIR / "alembic" / "versions" / "0012_menu_item_description_reconcile.py"
        ).read_text(encoding="utf-8")
        require(
            "long Alembic revision widens PostgreSQL version column",
            '"alembic_version"' in reconcile_source and "String(length=64)" in reconcile_source,
            reconcile_source,
        )

        os.environ["DATABASE_URL"] = "sqlite:///:memory:"
        from src import store
        from src.db_models import OperatorSession

        operator_lookup = inspect.getsource(store.get_operator_session)
        operator_cleanup = inspect.getsource(store.cleanup_expired_auth_records)
        require(
            "ORM supplies created_at",
            OperatorSession.__table__.c.created_at.default is not None,
        )
        require("operator auth uses expires_at", "OperatorSession.expires_at" in operator_lookup, operator_lookup)
        require("operator cleanup uses expires_at", "OperatorSession.expires_at" in operator_cleanup, operator_cleanup)
        require("operator auth does not use created_at", "OperatorSession.created_at" not in operator_lookup, operator_lookup)
    except Exception as exc:
        print(json.dumps({"status": "failed", "finding": finding, "error": f"{type(exc).__name__}: {exc}"}, indent=2))
        raise SystemExit(1)
    print(
        json.dumps(
            {
                "status": "ok",
                "finding": finding,
                "notes": [
                    "SQLite compiles server time as CURRENT_TIMESTAMP.",
                    "PostgreSQL compiles server time as now().",
                    "created_at is informational; expires_at alone controls authentication expiry.",
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
