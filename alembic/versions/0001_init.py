"""Initial schema for multi-tenant, menu, orders, reservations."""
from alembic import op
import sqlalchemy as sa

revision = "0001_init"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    json_empty_obj = sa.text("'{}'")
    json_empty_arr = sa.text("'[]'")

    op.create_table(
        "tenants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.String(length=64), nullable=False, unique=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("admin_chat_id", sa.BigInteger(), nullable=True),
        sa.Column("features", sa.JSON(), nullable=False, server_default=json_empty_obj),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "menu_categories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("sort", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("tenant_id", "title", name="uq_category_title_per_tenant"),
    )
    op.create_index("ix_menu_categories_tenant_id", "menu_categories", ["tenant_id"])

    op.create_table(
        "menu_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category_id", sa.Integer(), sa.ForeignKey("menu_categories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("price", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_menu_items_tenant_id", "menu_items", ["tenant_id"])

    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="site"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="new"),
        sa.Column("items", sa.JSON(), nullable=False, server_default=json_empty_arr),
        sa.Column("total", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("customer_name", sa.String(length=255), nullable=True),
        sa.Column("customer_phone", sa.String(length=64), nullable=True),
        sa.Column("customer_address", sa.Text(), nullable=True),
        sa.Column("raw_payload", sa.JSON(), nullable=True),
    )
    op.create_index("ix_orders_tenant_id", "orders", ["tenant_id"])

    op.create_table(
        "bot_users",
        sa.Column("user_id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True),
        sa.Column("slug", sa.String(length=64), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_bot_users_tenant_id", "bot_users", ["tenant_id"])

    op.create_table(
        "tables",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index("ix_tables_tenant_id", "tables", ["tenant_id"])

    op.create_table(
        "reservations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("table_id", sa.Integer(), sa.ForeignKey("tables.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("phone", sa.String(length=64), nullable=False),
        sa.Column("datetime", sa.DateTime(), nullable=False),
        sa.Column("guests", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="new"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_reservations_tenant_id", "reservations", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_reservations_tenant_id", table_name="reservations")
    op.drop_table("reservations")
    op.drop_index("ix_tables_tenant_id", table_name="tables")
    op.drop_table("tables")
    op.drop_index("ix_bot_users_tenant_id", table_name="bot_users")
    op.drop_table("bot_users")
    op.drop_index("ix_orders_tenant_id", table_name="orders")
    op.drop_table("orders")
    op.drop_index("ix_menu_items_tenant_id", table_name="menu_items")
    op.drop_table("menu_items")
    op.drop_index("ix_menu_categories_tenant_id", table_name="menu_categories")
    op.drop_table("menu_categories")
    op.drop_table("tenants")
