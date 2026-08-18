"""Add tenant timezone for local promotion schedules."""

from alembic import op
import sqlalchemy as sa


revision = "0015_tenant_timezone"
down_revision = "0014_operator_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column(
            "timezone",
            sa.String(length=64),
            nullable=False,
            server_default="Asia/Tashkent",
        ),
    )


def downgrade() -> None:
    op.drop_column("tenants", "timezone")
