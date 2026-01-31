"""Add customer_chat_id to orders."""
from alembic import op
import sqlalchemy as sa

revision = "0002_order_customer_chat"
down_revision = "0001_init"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("customer_chat_id", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "customer_chat_id")
