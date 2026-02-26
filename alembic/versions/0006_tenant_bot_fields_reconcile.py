"""Reconciliation checkpoint after tenant bot fields migration."""

revision = "0006_tenant_bot_fields_safe"
down_revision = "0005_order_customer_chat_id_safe"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Fields were introduced in revision 0004_tenant_bot_fields.
    # Keep this revision as a compatibility marker only.
    pass


def downgrade() -> None:
    pass
