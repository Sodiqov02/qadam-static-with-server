"""Add tenant branding fields."""

from alembic import op
import sqlalchemy as sa


revision = "0013_tenant_branding_fields"
down_revision = "0012_menu_item_description_reconcile"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenants", sa.Column("logo_url", sa.String(length=1024), nullable=True))
    op.add_column("tenants", sa.Column("primary_color", sa.String(length=16), nullable=True))
    op.add_column("tenants", sa.Column("accent_color", sa.String(length=16), nullable=True))
    op.add_column(
        "tenants",
        sa.Column("theme_mode", sa.String(length=32), nullable=False, server_default="default"),
    )


def downgrade() -> None:
    op.drop_column("tenants", "theme_mode")
    op.drop_column("tenants", "accent_color")
    op.drop_column("tenants", "primary_color")
    op.drop_column("tenants", "logo_url")
