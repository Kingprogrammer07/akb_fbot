"""Add is_used column to cargo_items

Revision ID: f3d8e9a2b1c4
Revises: 14a85afee594
Create Date: 2026-01-02 17:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f3d8e9a2b1c4'
down_revision: Union[str, None] = '14a85afee594'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add is_used column to cargo_items table."""
    op.add_column(
        'cargo_items',
        sa.Column(
            'is_used',
            sa.Boolean(),
            nullable=False,
            server_default='false',
            comment='Flag to track if cargo item has been used'
        )
    )


def downgrade() -> None:
    """Remove is_used column from cargo_items table."""
    op.drop_column('cargo_items', 'is_used')
