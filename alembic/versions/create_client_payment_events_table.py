"""Create client_payment_events table

Revision ID: create_payment_events
Revises: add_partial_payment
Create Date: 2026-01-22 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'create_payment_events'
down_revision: Union[str, None] = 'add_partial_payment'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create client_payment_events table and migrate existing data."""
    # Create client_payment_events table
    op.create_table(
        'client_payment_events',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            'transaction_id',
            sa.Integer(),
            nullable=False,
            comment='Foreign key to client_transaction_data.id'
        ),
        sa.Column(
            'payment_type',
            sa.String(length=10),
            nullable=False,
            comment="Payment type: 'online' or 'cash'"
        ),
        sa.Column(
            'amount',
            sa.Numeric(precision=12, scale=2),
            nullable=False,
            comment='Payment amount'
        ),
        sa.Column(
            'created_at',
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text('CURRENT_TIMESTAMP'),
            comment='When the payment event was created'
        ),
        sa.Column(
            'approved_by_admin_id',
            sa.BigInteger(),
            nullable=True,
            comment='Telegram ID of admin who approved this payment'
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(
            ['transaction_id'],
            ['client_transaction_data.id'],
            ondelete='CASCADE'
        )
    )
    
    # Create index on transaction_id for faster queries
    op.create_index(
        'ix_client_payment_events_transaction_id',
        'client_payment_events',
        ['transaction_id']
    )
    
    # Create index on created_at for sorting
    op.create_index(
        'ix_client_payment_events_created_at',
        'client_payment_events',
        ['created_at']
    )
    
    # Migrate existing transactions to payment events
    # Each existing transaction becomes a single payment event
    op.execute("""
        INSERT INTO client_payment_events (transaction_id, payment_type, amount, created_at, approved_by_admin_id)
        SELECT 
            id as transaction_id,
            COALESCE(payment_type, 'online') as payment_type,
            COALESCE(paid_amount, summa, 0) as amount,
            COALESCE(created_at, CURRENT_TIMESTAMP) as created_at,
            NULL as approved_by_admin_id
        FROM client_transaction_data
        WHERE COALESCE(paid_amount, summa, 0) > 0
    """)


def downgrade() -> None:
    """Drop client_payment_events table."""
    op.drop_index('ix_client_payment_events_created_at', table_name='client_payment_events')
    op.drop_index('ix_client_payment_events_transaction_id', table_name='client_payment_events')
    op.drop_table('client_payment_events')

