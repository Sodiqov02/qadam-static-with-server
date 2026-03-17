"""Add admin login tokens and admin sessions tables."""
from alembic import op
import sqlalchemy as sa

revision = "0011_admin_auth_tables"
down_revision = "0010_menu_category_sort_order"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admin_login_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token", sa.String(length=255), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_admin_login_tokens_tenant_id", "admin_login_tokens", ["tenant_id"])
    op.create_index("ix_admin_login_tokens_token", "admin_login_tokens", ["token"], unique=True)

    op.create_table(
        "admin_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("session_token", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_admin_sessions_tenant_id", "admin_sessions", ["tenant_id"])
    op.create_index("ix_admin_sessions_session_token", "admin_sessions", ["session_token"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_admin_sessions_session_token", table_name="admin_sessions")
    op.drop_index("ix_admin_sessions_tenant_id", table_name="admin_sessions")
    op.drop_table("admin_sessions")

    op.drop_index("ix_admin_login_tokens_token", table_name="admin_login_tokens")
    op.drop_index("ix_admin_login_tokens_tenant_id", table_name="admin_login_tokens")
    op.drop_table("admin_login_tokens")
