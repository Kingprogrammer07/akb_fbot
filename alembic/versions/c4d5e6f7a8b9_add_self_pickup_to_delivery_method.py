"""add self_pickup to delivery_method check constraint

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-04-06 00:00:00.000000

Why: The application now supports a "self_pickup" delivery method for
cargo_delivery_proofs, but the existing CHECK constraint only allowed
uzpost, bts, akb, and yandex.  This migration extends the constraint
to include the new value.
"""

from __future__ import annotations

from alembic import op

revision: str = "c4d5e6f7a8b9"
down_revision: str = "b3c4d5e6f7a8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE cargo_delivery_proofs "
        "DROP CONSTRAINT IF EXISTS check_delivery_method_values"
    )
    op.execute(
        "ALTER TABLE cargo_delivery_proofs "
        "ADD CONSTRAINT check_delivery_method_values "
        "CHECK (delivery_method IN ('uzpost', 'bts', 'akb', 'yandex', 'self_pickup'))"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE cargo_delivery_proofs "
        "DROP CONSTRAINT IF EXISTS check_delivery_method_values"
    )
    op.execute(
        "ALTER TABLE cargo_delivery_proofs "
        "ADD CONSTRAINT check_delivery_method_values "
        "CHECK (delivery_method IN ('uzpost', 'bts', 'akb', 'yandex'))"
    )
