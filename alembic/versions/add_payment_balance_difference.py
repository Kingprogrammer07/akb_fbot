"""Add payment_balance_difference to client_transaction_data

Revision ID: add_payment_balance_diff
Revises: add_notification_fields
Create Date: 2026-01-24 12:00:00.000000

This migration adds the payment_balance_difference column to track
the difference between paid_amount and expected_amount.
Negative values indicate debt, positive values indicate overpayment.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'add_payment_balance_diff'
down_revision: Union[str, None] = 'add_notification_fields'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def column_exists(table_name: str, column_name: str) -> bool:
    """Check if a column exists in the given table."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def upgrade() -> None:
    """Add payment_balance_difference column to client_transaction_data."""
    if not column_exists('client_transaction_data', 'payment_balance_difference'):
        op.add_column(
            'client_transaction_data',
            sa.Column(
                'payment_balance_difference',
                sa.Numeric(precision=12, scale=2),
                nullable=False,
                server_default='0',
                comment="Difference between paid_amount and expected_amount (negative=debt, positive=overpaid)"
            )
        )

    # Update existing records: set payment_balance_difference = 0 for all existing transactions
    # (existing transactions are assumed to be fully paid without difference)
    op.execute("""
        UPDATE client_transaction_data
        SET payment_balance_difference = 0
        WHERE payment_balance_difference IS NULL
    """)


def downgrade() -> None:
    """Remove payment_balance_difference column."""
    if column_exists('client_transaction_data', 'payment_balance_difference'):
        op.drop_column('client_transaction_data', 'payment_balance_difference')
