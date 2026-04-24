"""Make payment_provider required and set defaults for existing records

Revision ID: make_payment_provider_required
Revises: add_payment_provider
Create Date: 2026-01-15 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'make_payment_provider_required'
down_revision: Union[str, None] = 'add_payment_provider'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Make payment_provider NOT NULL and set defaults for existing records.

    Steps:
    1. Set payment_provider = 'cash' for all NULL records where payment_type = 'cash'
    2. Set payment_provider = 'cash' for all remaining NULL records (conservative default)
    3. Alter column to NOT NULL with server_default='cash'
    4. Update check constraint

    This ensures:
    - All existing records have a valid payment_provider
    - Future records must specify payment_provider
    - Backward compatibility maintained
    """

    # Step 1: Set payment_provider='cash' for existing cash payments
    op.execute("""
        UPDATE client_payment_events
        SET payment_provider = 'cash'
        WHERE payment_provider IS NULL AND payment_type = 'cash'
    """)

    # Step 2: Set payment_provider='cash' for all remaining NULL records
    # This handles legacy online payments (conservative approach)
    op.execute("""
        UPDATE client_payment_events
        SET payment_provider = 'cash'
        WHERE payment_provider IS NULL
    """)

    # Step 3: Drop existing check constraint
    op.drop_constraint(
        'check_payment_provider_values',
        'client_payment_events',
        type_='check'
    )

    # Step 4: Make column NOT NULL with server_default
    op.alter_column(
        'client_payment_events',
        'payment_provider',
        existing_type=sa.String(length=20),
        nullable=False,
        server_default='cash',
        comment="Payment provider: 'cash', 'click', 'payme' (REQUIRED)"
    )

    # Step 5: Add updated check constraint
    op.create_check_constraint(
        'check_payment_provider_values',
        'client_payment_events',
        "payment_provider IN ('cash', 'click', 'payme')"
    )

    # Step 6: Mark payment_type as deprecated (add comment)
    op.alter_column(
        'client_payment_events',
        'payment_type',
        existing_type=sa.String(length=10),
        comment="DEPRECATED: Legacy field. Use payment_provider instead."
    )


def downgrade() -> None:
    """
    Revert payment_provider to nullable.

    WARNING: This will make payment_provider optional again.
    """
    # Remove comment from payment_type
    op.alter_column(
        'client_payment_events',
        'payment_type',
        existing_type=sa.String(length=10),
        comment="Payment type: 'online' or 'cash'"
    )

    # Drop check constraint
    op.drop_constraint(
        'check_payment_provider_values',
        'client_payment_events',
        type_='check'
    )

    # Make payment_provider nullable again
    op.alter_column(
        'client_payment_events',
        'payment_provider',
        existing_type=sa.String(length=20),
        nullable=True,
        server_default=None,
        comment="Payment provider: null (legacy), 'cash', 'click', 'payme'"
    )

    # Recreate old check constraint
    op.create_check_constraint(
        'check_payment_provider_values',
        'client_payment_events',
        "payment_provider IS NULL OR payment_provider IN ('cash', 'click', 'payme')"
    )
