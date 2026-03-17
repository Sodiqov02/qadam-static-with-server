"""Add sort_order to menu_categories and backfill from legacy sort."""
from alembic import op
import sqlalchemy as sa

revision = "0010_menu_category_sort_order"
down_revision = "0009_menu_item_image_path"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("menu_categories")}
    if "sort_order" in columns:
        return

    with op.batch_alter_table("menu_categories") as batch_op:
        batch_op.add_column(sa.Column("sort_order", sa.Integer(), nullable=True, server_default="0"))

    bind.execute(sa.text("UPDATE menu_categories SET sort_order = COALESCE(sort, 0) WHERE sort_order IS NULL"))

    with op.batch_alter_table("menu_categories") as batch_op:
        batch_op.alter_column("sort_order", existing_type=sa.Integer(), nullable=False, server_default="0")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("menu_categories")}
    if "sort_order" not in columns:
        return

    with op.batch_alter_table("menu_categories") as batch_op:
        batch_op.drop_column("sort_order")
