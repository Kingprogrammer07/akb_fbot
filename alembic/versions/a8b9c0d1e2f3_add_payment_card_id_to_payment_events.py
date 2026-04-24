"""add payment_card_id to client_payment_events

Revision ID: a8b9c0d1e2f3
Revises: 1f86d0a0650e
Create Date: 2026-04-18 00:00:00.000000

Why:
  Each payment event should record which company card the client paid to.
  This enables per-card balance tracking: SUM(amount) WHERE payment_card_id = X.
  Nullable so existing rows and non-card payments (cash, wallet) are unaffected.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "a8b9c0d1e2f3"
down_revision: str = "1f86d0a0650e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "client_payment_events",
        sa.Column(
            "payment_card_id",
            sa.Integer(),
            sa.ForeignKey("payment_cards.id", ondelete="SET NULL"),
            nullable=True,
            comment="Which company card this payment was received on (NULL for cash/wallet)",
        ),
    )
    op.create_index(
        "ix_client_payment_events_payment_card_id",
        "client_payment_events",
        ["payment_card_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_client_payment_events_payment_card_id",
        table_name="client_payment_events",
    )
    op.drop_column("client_payment_events", "payment_card_id")
