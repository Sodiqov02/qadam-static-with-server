"""Remove legacy default tenant seed."""
from alembic import op
import sqlalchemy as sa

revision = "0007_drop_default_tenant"
down_revision = "0006_tenant_bot_fields_safe"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind is None:
        return
    bind.execute(sa.text("DELETE FROM tenants WHERE slug = :slug"), {"slug": "default"})


def downgrade() -> None:
    bind = op.get_bind()
    if bind is None:
        return
    exists = bind.execute(
        sa.text("SELECT 1 FROM tenants WHERE slug = :slug LIMIT 1"),
        {"slug": "default"},
    ).fetchone()
    if exists:
        return
    bind.execute(
        sa.text(
            """
            INSERT INTO tenants (slug, name, admin_chat_id, features, is_active)
            VALUES (:slug, :name, NULL, :features, TRUE)
            """
        ),
        {"slug": "default", "name": "Default tenant", "features": "{}"},
    )
