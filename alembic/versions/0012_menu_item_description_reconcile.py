"""Reconcile menu item description column if missing."""

from alembic import op
import sqlalchemy as sa


revision = "0012_menu_item_description_reconcile"
down_revision = "0011_admin_auth_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    # Alembic creates version_num as VARCHAR(32), but this revision identifier
    # is longer. SQLite does not enforce that width; PostgreSQL does and must
    # be widened before Alembic records this revision after upgrade().
    if connection.dialect.name != "sqlite":
        op.alter_column(
            "alembic_version",
            "version_num",
            existing_type=sa.String(length=32),
            type_=sa.String(length=64),
            existing_nullable=False,
        )
    inspector = sa.inspect(connection)
    columns = {column["name"] for column in inspector.get_columns("menu_items")}
    if "description" not in columns:
        op.add_column("menu_items", sa.Column("description", sa.Text(), nullable=True))


def downgrade() -> None:
    # This migration is a reconcile step and may be a no-op on databases
    # where the column already existed, so downgrade intentionally does nothing.
    return
