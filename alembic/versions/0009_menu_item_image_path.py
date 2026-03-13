"""Add image_path to menu_items and backfill from existing image URLs."""
from alembic import op
import sqlalchemy as sa

revision = "0009_menu_item_image_path"
down_revision = "0008_menu_item_image_url"
branch_labels = None
depends_on = None


def _extract_image_path(image_url: str | None) -> str | None:
    if not image_url:
        return None
    value = str(image_url).strip()
    if not value:
        return None
    if value.startswith("/menu-images/"):
        return value[len("/menu-images/"):].strip("/") or None
    if value.startswith("/uploads/"):
        parts = value[len("/uploads/"):].strip("/").split("/")
        if len(parts) >= 3 and parts[1] == "menu":
            return f"{parts[0]}/{'/'.join(parts[2:])}"
    return None


def upgrade() -> None:
    op.add_column("menu_items", sa.Column("image_path", sa.String(length=1024), nullable=True))

    connection = op.get_bind()
    rows = connection.execute(sa.text("SELECT id, image_url FROM menu_items WHERE image_url IS NOT NULL")).fetchall()
    for row in rows:
        image_path = _extract_image_path(row.image_url)
        if not image_path:
            continue
        connection.execute(
            sa.text("UPDATE menu_items SET image_path = :image_path WHERE id = :item_id"),
            {"image_path": image_path, "item_id": row.id},
        )


def downgrade() -> None:
    op.drop_column("menu_items", "image_path")
