"""Add image_url to menu_items."""
from alembic import op
import sqlalchemy as sa

revision = "0008_menu_item_image_url"
down_revision = "0007_drop_default_tenant"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("menu_items", sa.Column("image_url", sa.String(length=1024), nullable=True))


def downgrade() -> None:
    op.drop_column("menu_items", "image_url")
