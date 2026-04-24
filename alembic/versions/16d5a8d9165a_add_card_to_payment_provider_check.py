"""add_card_to_payment_provider_check

Revision ID: 16d5a8d9165a
Revises: create_user_payment_cards
Create Date: 2026-01-30 01:26:45.991960

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '16d5a8d9165a'
down_revision: Union[str, None] = 'create_user_payment_cards'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("""
        ALTER TABLE client_payment_events
        DROP CONSTRAINT IF EXISTS check_payment_provider_values;
    """)
    op.execute("""
        ALTER TABLE client_payment_events
        ADD CONSTRAINT check_payment_provider_values
        CHECK (payment_provider IN ('cash', 'click', 'payme', 'card'));
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("""
        ALTER TABLE client_payment_events
        DROP CONSTRAINT IF EXISTS check_payment_provider_values;
    """)
    op.execute("""
        ALTER TABLE client_payment_events
        ADD CONSTRAINT check_payment_provider_values
        CHECK (payment_provider IN ('cash', 'click', 'payme'));
    """)
