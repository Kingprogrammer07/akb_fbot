"""Add updated_at column to client_payment_events table

Revision ID: add_updated_at_to_payment_events
Revises: create_payment_events
Create Date: 2026-01-22 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'add_updated_at_to_payment_events'
down_revision: Union[str, None] = 'create_payment_events'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add updated_at column to client_payment_events table."""
    # Add updated_at column as nullable TIMESTAMP WITH TIME ZONE
    op.add_column(
        'client_payment_events',
        sa.Column(
            'updated_at',
            sa.TIMESTAMP(timezone=True),
            nullable=True,
            comment='Timestamp when payment event was last updated'
        )
    )
    
    # Backfill existing rows: set updated_at = created_at
    op.execute("""
        UPDATE client_payment_events
        SET updated_at = created_at
        WHERE updated_at IS NULL
    """)


def downgrade() -> None:
    """Remove updated_at column from client_payment_events table."""
    op.drop_column('client_payment_events', 'updated_at')

