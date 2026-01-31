"""Add promotions table."""
from alembic import op
import sqlalchemy as sa

revision = "0003_promotions"
down_revision = "0002_order_customer_chat"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "promotions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("menu_items.id", ondelete="SET NULL"), nullable=True),
        sa.Column("discount_percent", sa.Integer(), nullable=True),
        sa.Column("start_time", sa.Time(), nullable=True),
        sa.Column("end_time", sa.Time(), nullable=True),
        sa.Column("days_of_week", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_promotions_tenant_id", "promotions", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_promotions_tenant_id", table_name="promotions")
    op.drop_table("promotions")
