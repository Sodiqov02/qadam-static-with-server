"""Reconcile menu item description column if missing."""

from alembic import op
import sqlalchemy as sa


revision = "0012_menu_item_description_reconcile"
down_revision = "0011_admin_auth_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    columns = {column["name"] for column in inspector.get_columns("menu_items")}
    if "description" not in columns:
        op.add_column("menu_items", sa.Column("description", sa.Text(), nullable=True))


def downgrade() -> None:
    # This migration is a reconcile step and may be a no-op on databases
    # where the column already existed, so downgrade intentionally does nothing.
    return
