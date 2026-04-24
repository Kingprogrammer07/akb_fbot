"""Add partial payment fields to client_transaction_data

Revision ID: add_partial_payment
Revises: add_payment_type
Create Date: 2026-01-21 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'add_partial_payment'
down_revision: Union[str, None] = 'add_payment_type'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add partial payment columns to client_transaction_data."""
    # Add payment_status column (String instead of ENUM for compatibility)
    op.add_column(
        'client_transaction_data',
        sa.Column(
            'payment_status',
            sa.String(length=10),
            nullable=False,
            server_default='paid',
            comment="Payment status: 'pending', 'partial', or 'paid'"
        )
    )
    
    # Add paid_amount column
    op.add_column(
        'client_transaction_data',
        sa.Column(
            'paid_amount',
            sa.Numeric(precision=12, scale=2),
            nullable=False,
            server_default='0',
            comment="Amount already paid (for partial payments)"
        )
    )
    
    # Add total_amount column
    op.add_column(
        'client_transaction_data',
        sa.Column(
            'total_amount',
            sa.Numeric(precision=12, scale=2),
            nullable=True,
            comment="Total amount required (snapshot at first payment)"
        )
    )
    
    # Add remaining_amount column
    op.add_column(
        'client_transaction_data',
        sa.Column(
            'remaining_amount',
            sa.Numeric(precision=12, scale=2),
            nullable=False,
            server_default='0',
            comment="Remaining amount to be paid"
        )
    )
    
    # Add payment_deadline column
    op.add_column(
        'client_transaction_data',
        sa.Column(
            'payment_deadline',
            sa.TIMESTAMP(timezone=True),
            nullable=True,
            comment="Payment deadline (15 days from first payment, nullable)"
        )
    )
    
    # Update existing records: set payment_status='paid', paid_amount=summa, total_amount=summa, remaining_amount=0
    op.execute("""
        UPDATE client_transaction_data
        SET 
            payment_status = 'paid',
            paid_amount = summa,
            total_amount = summa,
            remaining_amount = 0
    """)


def downgrade() -> None:
    """Remove partial payment columns."""
    op.drop_column('client_transaction_data', 'payment_deadline')
    op.drop_column('client_transaction_data', 'remaining_amount')
    op.drop_column('client_transaction_data', 'total_amount')
    op.drop_column('client_transaction_data', 'paid_amount')
    op.drop_column('client_transaction_data', 'payment_status')

