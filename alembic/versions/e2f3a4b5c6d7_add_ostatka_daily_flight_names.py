"""add static_data.ostatka_daily_flight_names

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-04-24 11:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "e2f3a4b5c6d7"
down_revision: str = "d1e2f3a4b5c6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "static_data",
        sa.Column(
            "ostatka_daily_flight_names",
            sa.Text(),
            nullable=False,
            server_default="'[]'",
        ),
    )


def downgrade() -> None:
    op.drop_column("static_data", "ostatka_daily_flight_names")
