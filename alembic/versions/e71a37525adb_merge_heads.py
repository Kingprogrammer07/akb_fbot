"""merge heads

Revision ID: e71a37525adb
Revises: aaa632e59528, add_custom_usd_rate
Create Date: 2026-02-25 01:10:52.020818

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e71a37525adb'
down_revision: Union[str, None] = ('aaa632e59528', 'add_custom_usd_rate')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
