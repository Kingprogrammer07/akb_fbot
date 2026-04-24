"""merge_heads_notification

Revision ID: eb3f22e612e3
Revises: add_notification_fields, d5e6f7a8b9c0
Create Date: 2026-01-05 17:44:13.069701

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'eb3f22e612e3'
down_revision: Union[str, None] = ('add_notification_fields', 'd5e6f7a8b9c0')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
