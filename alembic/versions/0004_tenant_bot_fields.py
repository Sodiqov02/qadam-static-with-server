"""Add tenant bot fields."""
from alembic import op
import sqlalchemy as sa

revision = "0004_tenant_bot_fields"
down_revision = "0003_promotions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenants", sa.Column("bot_token", sa.String(length=255), nullable=True))
    op.add_column("tenants", sa.Column("bot_username", sa.String(length=255), nullable=True))
    op.add_column("tenants", sa.Column("bot_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("tenants", "bot_enabled")
    op.drop_column("tenants", "bot_username")
    op.drop_column("tenants", "bot_token")
