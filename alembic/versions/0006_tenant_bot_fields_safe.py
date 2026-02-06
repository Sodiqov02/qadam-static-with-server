"""Ensure tenant bot fields exist (idempotent)."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0006_tenant_bot_fields_safe"
down_revision = "0005_order_customer_chat_id_safe"
branch_labels = None
depends_on = None


def _get_column_names(bind) -> set[str]:
    inspector = inspect(bind)
    return {col["name"] for col in inspector.get_columns("tenants")}


def upgrade() -> None:
    bind = op.get_bind()
    columns = _get_column_names(bind)

    if "bot_token" not in columns:
        op.add_column("tenants", sa.Column("bot_token", sa.String(length=255), nullable=True))

    if "bot_username" not in columns:
        op.add_column("tenants", sa.Column("bot_username", sa.String(length=255), nullable=True))

    if "bot_enabled" not in columns:
        op.add_column(
            "tenants",
            sa.Column("bot_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        )


def downgrade() -> None:
    bind = op.get_bind()
    columns = _get_column_names(bind)

    if "bot_enabled" in columns:
        op.drop_column("tenants", "bot_enabled")

    if "bot_username" in columns:
        op.drop_column("tenants", "bot_username")

    if "bot_token" in columns:
        op.drop_column("tenants", "bot_token")
