"""Ensure orders.customer_chat_id exists (hotfix)."""
from alembic import op
import sqlalchemy as sa

revision = "0005_order_customer_chat_id_safe"
down_revision = "0004_tenant_bot_fields"
branch_labels = None
depends_on = None


def _column_exists(bind, table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(bind)
    cols = [c.get("name") for c in inspector.get_columns(table_name)]
    return column_name in cols


def upgrade() -> None:
    bind = op.get_bind()
    if bind is None:
        return
    if not _column_exists(bind, "orders", "customer_chat_id"):
        op.add_column("orders", sa.Column("customer_chat_id", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if bind is None:
        return
    if _column_exists(bind, "orders", "customer_chat_id"):
        op.drop_column("orders", "customer_chat_id")
