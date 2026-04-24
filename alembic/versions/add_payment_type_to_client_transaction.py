"""Add payment_type to client_transaction_data

Revision ID: add_payment_type
Revises: eb3f22e612e3
Create Date: 2026-01-20 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'add_payment_type'
down_revision: Union[str, None] = 'eb3f22e612e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add payment_type column to client_transaction_data."""
    op.add_column(
        'client_transaction_data',
        sa.Column(
            'payment_type',
            sa.String(length=10),
            nullable=False,
            server_default='online',
            comment="Payment type: 'online' or 'cash'"
        )
    )


def downgrade() -> None:
    """Remove payment_type column."""
    op.drop_column('client_transaction_data', 'payment_type')

