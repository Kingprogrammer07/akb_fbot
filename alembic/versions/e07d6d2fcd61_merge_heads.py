"""merge heads

Revision ID: e07d6d2fcd61
Revises: add_payment_balance_diff, change_broadcast_ids_bigint
Create Date: 2026-01-24 01:16:27.371327

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e07d6d2fcd61'
down_revision: Union[str, None] = ('add_payment_balance_diff', 'change_broadcast_ids_bigint')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
