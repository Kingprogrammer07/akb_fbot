"""Add payment_provider column to client_payment_events

Revision ID: add_payment_provider
Revises: create_stats_aggregation_tables
Create Date: 2026-01-15 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'add_payment_provider'
down_revision: Union[str, None] = 'create_stats_aggregation_tables'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Add payment_provider column to client_payment_events table.

    This column tracks which payment provider was used:
    - 'cash' - Cash payment
    - 'click' - Click payment provider
    - 'payme' - Payme payment provider
    - NULL - Legacy records (backward compatibility)

    Steps:
    1. Add nullable column (safe for existing rows)
    2. Add comment for documentation
    3. Create index for statistics queries
    4. Add check constraint for valid values
    5. Migrate existing cash payments (optional data migration)
    """
    # Step 1: Add payment_provider column (nullable for backward compatibility)
    op.add_column(
        'client_payment_events',
        sa.Column(
            'payment_provider',
            sa.String(length=20),
            nullable=True,
            comment="Payment provider: 'cash', 'click', 'payme', or NULL (legacy)"
        )
    )

    # Step 2: Create index for efficient provider-based queries
    op.create_index(
        'ix_client_payment_events_provider',
        'client_payment_events',
        ['payment_provider'],
        unique=False
    )

    # Step 3: Add check constraint to ensure valid values
    op.create_check_constraint(
        'check_payment_provider_values',
        'client_payment_events',
        "payment_provider IS NULL OR payment_provider IN ('cash', 'click', 'payme')"
    )

    # Step 4: Data migration - Update existing cash payments
    # Set payment_provider = 'cash' for existing cash payment events
    # This is optional but recommended for consistency
    op.execute("""
        UPDATE client_payment_events
        SET payment_provider = 'cash'
        WHERE payment_type = 'cash' AND payment_provider IS NULL
    """)

    # Note: Existing online payments keep payment_provider = NULL
    # This preserves backward compatibility and distinguishes them from
    # new account payments (Click/Payme)


def downgrade() -> None:
    """
    Remove payment_provider column and related objects.

    WARNING: This will lose payment provider information for Click/Payme payments.
    Only run this if you're certain you want to remove the feature.
    """
    # Remove check constraint
    op.drop_constraint(
        'check_payment_provider_values',
        'client_payment_events',
        type_='check'
    )

    # Remove index
    op.drop_index(
        'ix_client_payment_events_provider',
        table_name='client_payment_events'
    )

    # Remove column (data will be lost)
    op.drop_column('client_payment_events', 'payment_provider')
