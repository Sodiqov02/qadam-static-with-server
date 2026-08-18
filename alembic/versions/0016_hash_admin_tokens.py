"""Hash persisted admin login and session bearer tokens."""

import hashlib

from alembic import op
import sqlalchemy as sa


revision = "0016_hash_admin_tokens"
down_revision = "0015_tenant_timezone"
branch_labels = None
depends_on = None


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _is_token_hash(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _hash_column(table_name: str, column_name: str) -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(f"SELECT id, {column_name} FROM {table_name}")
    ).mappings().all()
    for row in rows:
        raw_token = str(row[column_name])
        if _is_token_hash(raw_token):
            continue
        connection.execute(
            sa.text(
                f"UPDATE {table_name} SET {column_name} = :token_hash WHERE id = :row_id"
            ),
            {"token_hash": _token_hash(raw_token), "row_id": row["id"]},
        )


def upgrade() -> None:
    _hash_column("admin_login_tokens", "token")
    _hash_column("admin_sessions", "session_token")


def downgrade() -> None:
    # SHA-256 is intentionally irreversible. A code downgrade invalidates the
    # original cookies/links and must not serve auth against these hashed rows.
    pass
