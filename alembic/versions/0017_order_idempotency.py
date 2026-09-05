"""Add tenant-scoped checkout idempotency fields."""

from alembic import op
import sqlalchemy as sa


revision = "0017_order_idempotency"
down_revision = "0016_hash_admin_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("orders") as batch_op:
        batch_op.add_column(sa.Column("idempotency_key", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("idempotency_fingerprint", sa.String(length=64), nullable=True))
        batch_op.create_unique_constraint(
            "uq_order_idempotency_per_tenant",
            ["tenant_id", "idempotency_key"],
        )


def downgrade() -> None:
    with op.batch_alter_table("orders") as batch_op:
        batch_op.drop_constraint("uq_order_idempotency_per_tenant", type_="unique")
        batch_op.drop_column("idempotency_fingerprint")
        batch_op.drop_column("idempotency_key")
