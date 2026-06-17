"""repair akb delivery method constraint

Revision ID: p8q9r0s1t2u3
Revises: p7z8r9e0d1w2
Create Date: 2026-06-17 00:00:00.000000

Some production databases still allowed ``mandarin`` instead of ``akb`` in
cargo_delivery_proofs.delivery_method. The application sends ``akb``, so
those databases rejected warehouse mark-taken proof inserts.
"""

from __future__ import annotations

from alembic import op

revision: str = "p8q9r0s1t2u3"
down_revision: str = "p7z8r9e0d1w2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE cargo_delivery_proofs "
        "SET delivery_method = 'akb' "
        "WHERE delivery_method = 'mandarin'"
    )
    op.execute(
        "UPDATE delivery_requests "
        "SET delivery_type = 'akb' "
        "WHERE delivery_type = 'mandarin'"
    )
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
        "UPDATE cargo_delivery_proofs "
        "SET delivery_method = 'mandarin' "
        "WHERE delivery_method = 'akb'"
    )
    op.execute(
        "UPDATE delivery_requests "
        "SET delivery_type = 'mandarin' "
        "WHERE delivery_type = 'akb'"
    )
    op.execute(
        "ALTER TABLE cargo_delivery_proofs "
        "ADD CONSTRAINT check_delivery_method_values "
        "CHECK (delivery_method IN ('uzpost', 'bts', 'mandarin', 'yandex', 'self_pickup'))"
    )
