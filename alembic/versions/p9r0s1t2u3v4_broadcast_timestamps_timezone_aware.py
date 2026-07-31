"""make broadcast timestamps timezone aware

Revision ID: p9r0s1t2u3v4
Revises: p8q9r0s1t2u3
Create Date: 2026-07-31 00:00:00.000000

Broadcast creation and sender code use UTC-aware datetimes. The original
broadcast_messages migration created created_at, started_at, and completed_at
as TIMESTAMP WITHOUT TIME ZONE, which makes asyncpg reject aware datetimes.
"""

from __future__ import annotations

from alembic import op

revision: str = "p9r0s1t2u3v4"
down_revision: str = "p8q9r0s1t2u3"
branch_labels = None
depends_on = None

_COLUMNS = ("created_at", "started_at", "completed_at")


def upgrade() -> None:
    for column in _COLUMNS:
        op.execute(
            f"ALTER TABLE broadcast_messages "
            f"ALTER COLUMN {column} TYPE TIMESTAMP WITH TIME ZONE "
            f"USING {column} AT TIME ZONE 'UTC'"
        )


def downgrade() -> None:
    for column in _COLUMNS:
        op.execute(
            f"ALTER TABLE broadcast_messages "
            f"ALTER COLUMN {column} TYPE TIMESTAMP WITHOUT TIME ZONE "
            f"USING {column} AT TIME ZONE 'UTC'"
        )
