"""Add persistent operator sessions."""

from alembic import op
import sqlalchemy as sa


revision = "0014_operator_sessions"
down_revision = "0013_tenant_branding_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "operator_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_operator_sessions_token_hash", "operator_sessions", ["token_hash"], unique=True)
    op.create_index("ix_operator_sessions_expires_at", "operator_sessions", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_operator_sessions_expires_at", table_name="operator_sessions")
    op.drop_index("ix_operator_sessions_token_hash", table_name="operator_sessions")
    op.drop_table("operator_sessions")
