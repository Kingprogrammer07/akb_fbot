"""add index on client_payment_events.approved_by_admin_id

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-03-25 00:00:00.000000

Why this index exists:
  The POS cashier log endpoint (GET /payments/cashier-log) filters
  client_payment_events by approved_by_admin_id to show a cashier their own
  payment history.  Without an index, every query is a full table scan on a
  high-volume events table, which degrades linearly with data growth.
  A B-tree index reduces the lookup to O(log n).

  The column is intentionally not UNIQUE — many payment events can share
  the same admin_id (one cashier processes many payments).
"""
from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: str = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_client_payment_events_approved_by_admin_id",
        "client_payment_events",
        ["approved_by_admin_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_client_payment_events_approved_by_admin_id",
        table_name="client_payment_events",
    )
