"""merge_migration_conflicts

Revision ID: 19d9be761e4c
Revises: 16d5a8d9165a, create_session_logs_table
Create Date: 2026-02-03 14:40:28.000324

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '19d9be761e4c'
down_revision: Union[str, None] = ('16d5a8d9165a', 'create_session_logs_table')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
