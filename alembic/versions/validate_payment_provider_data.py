"""Validate payment_provider data integrity and add composite index

Revision ID: validate_payment_provider
Revises: make_payment_provider_required
Create Date: 2026-01-15 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'validate_payment_provider'
down_revision: Union[str, None] = 'make_payment_provider_required'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Validate data integrity and add performance indexes.

    Steps:
    1. Verify no NULL payment_provider exists (should be impossible after previous migration)
    2. Add composite index (transaction_id, payment_provider) for breakdown queries
    3. Add composite index (transaction_id, created_at) for event ordering
    4. Verify CHECK constraint exists
    """

    # Step 1: Data validation (will raise error if NULL found)
    op.execute("""
        DO $$
        DECLARE
            null_count INTEGER;
        BEGIN
            SELECT COUNT(*) INTO null_count
            FROM client_payment_events
            WHERE payment_provider IS NULL;

            IF null_count > 0 THEN
                RAISE EXCEPTION 'Found % records with NULL payment_provider. Run make_payment_provider_required first.', null_count;
            END IF;
        END $$;
    """)

    # Step 2: Add composite index for payment breakdown queries
    # This index speeds up: SELECT SUM(amount) GROUP BY payment_provider WHERE transaction_id = X
    op.create_index(
        'ix_client_payment_events_tx_provider',
        'client_payment_events',
        ['transaction_id', 'payment_provider'],
        unique=False
    )

    # Step 3: Add composite index for event ordering within transaction
    # This index speeds up: SELECT * WHERE transaction_id = X ORDER BY created_at
    op.create_index(
        'ix_client_payment_events_tx_created',
        'client_payment_events',
        ['transaction_id', 'created_at'],
        unique=False
    )

    # Step 4: Verify CHECK constraint exists
    op.execute("""
        DO $$
        DECLARE
            constraint_exists BOOLEAN;
        BEGIN
            SELECT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'check_payment_provider_values'
                AND conrelid = 'client_payment_events'::regclass
            ) INTO constraint_exists;

            IF NOT constraint_exists THEN
                RAISE EXCEPTION 'CHECK constraint check_payment_provider_values does not exist. Migration chain broken.';
            END IF;
        END $$;
    """)

    # Step 5: Validate data consistency (sum of events vs transaction.paid_amount)
    # This is informational only - will print warnings but not fail
    op.execute("""
        DO $$
        DECLARE
            inconsistent_count INTEGER;
        BEGIN
            SELECT COUNT(*) INTO inconsistent_count
            FROM (
                SELECT
                    cpe.transaction_id,
                    SUM(cpe.amount) as event_total,
                    ctd.paid_amount as tx_paid
                FROM client_payment_events cpe
                JOIN client_transaction_data ctd ON ctd.id = cpe.transaction_id
                GROUP BY cpe.transaction_id, ctd.paid_amount
                HAVING ABS(SUM(cpe.amount) - COALESCE(ctd.paid_amount, 0)) > 0.01
            ) inconsistent;

            IF inconsistent_count > 0 THEN
                RAISE WARNING 'Found % transactions where event sum != paid_amount. Run data audit script.', inconsistent_count;
            ELSE
                RAISE NOTICE 'Data validation passed: All transactions consistent.';
            END IF;
        END $$;
    """)


def downgrade() -> None:
    """Remove validation indexes."""
    op.drop_index('ix_client_payment_events_tx_created', table_name='client_payment_events')
    op.drop_index('ix_client_payment_events_tx_provider', table_name='client_payment_events')
