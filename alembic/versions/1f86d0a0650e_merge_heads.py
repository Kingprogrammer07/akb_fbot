"""Merge heads

Revision ID: 1f86d0a0650e
Revises: ab12c3d4e5f7, b7d2a5f6e8b1
Create Date: 2026-04-17 03:50:51.084557

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1f86d0a0650e'
down_revision: Union[str, None] = ('ab12c3d4e5f7', 'b7d2a5f6e8b1')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
