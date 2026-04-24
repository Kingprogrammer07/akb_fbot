"""add wallet to payment_provider check constraint

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-03-27 00:00:00.000000

Why: The POS adjust-balance endpoint creates ClientPaymentEvent rows with
payment_provider='wallet' to represent cashier-initiated balance adjustments
(SYS_ADJ transactions).  The POS bulk-payment endpoint also uses 'wallet'
when a cargo is paid entirely from the client's wallet balance.

The existing CHECK constraint only allows ('cash', 'click', 'payme', 'card'),
causing a CheckViolationError on every wallet-sourced event.
"""
from __future__ import annotations

from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: str = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE client_payment_events
        DROP CONSTRAINT IF EXISTS check_payment_provider_values;
    """)
    op.execute("""
        ALTER TABLE client_payment_events
        ADD CONSTRAINT check_payment_provider_values
        CHECK (payment_provider IN ('cash', 'click', 'payme', 'card', 'wallet'));
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE client_payment_events
        DROP CONSTRAINT IF EXISTS check_payment_provider_values;
    """)
    op.execute("""
        ALTER TABLE client_payment_events
        ADD CONSTRAINT check_payment_provider_values
        CHECK (payment_provider IN ('cash', 'click', 'payme', 'card'));
    """)
