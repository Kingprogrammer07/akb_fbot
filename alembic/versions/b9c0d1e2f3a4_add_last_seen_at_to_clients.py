"""add last_seen_at to clients

Revision ID: b9c0d1e2f3a4
Revises: a8b9c0d1e2f3
Create Date: 2026-04-22 00:00:00.000000

Why:
  We need to track when each client last interacted with the bot so that
  the daily scheduler can automatically set is_logged_in=False for clients
  who have been inactive for more than 30 days.  Without this column we
  have no reliable per-row signal for "last bot activity".
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "b9c0d1e2f3a4"
down_revision: str = "a8b9c0d1e2f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "clients",
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Timestamp of last bot interaction; updated by LastSeenMiddleware",
        ),
    )


def downgrade() -> None:
    op.drop_column("clients", "last_seen_at")
