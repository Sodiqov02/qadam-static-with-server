"""Reconciliation checkpoint after orders.customer_chat_id migration."""

revision = "0005_order_customer_chat_id_safe"
down_revision = "0004_tenant_bot_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Column was introduced in revision 0002_order_customer_chat.
    # Keep this revision as a compatibility marker only.
    pass


def downgrade() -> None:
    pass
