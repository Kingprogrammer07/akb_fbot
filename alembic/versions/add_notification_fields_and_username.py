"""Add notification fields and username

Revision ID: add_notification_fields
Revises: 541e4bddd45a
Create Date: 2026-01-15 12:00:00.000000

NOTE: This migration is now idempotent - it safely checks if columns exist
before attempting to add them.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'add_notification_fields'
down_revision: Union[str, None] = '541e4bddd45a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = 'a7f4c8d3e2b9'


def column_exists(table_name: str, column_name: str) -> bool:
    """Check if a column exists in the given table."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    # Safely handle if table doesn't exist yet (though dependency ensures it should)
    if table_name not in inspector.get_table_names():
        return False
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def upgrade() -> None:
    """Add notification fields to static_data and username to clients (idempotent)."""
    # Add notification fields to static_data (if not exists)
    if not column_exists('static_data', 'notification'):
        op.add_column(
            'static_data',
            sa.Column(
                'notification',
                sa.Boolean(),
                nullable=False,
                server_default='false',
                comment='Whether leftover cargo notifications are enabled'
            )
        )

    if not column_exists('static_data', 'notification_period'):
        op.add_column(
            'static_data',
            sa.Column(
                'notification_period',
                sa.Integer(),
                nullable=False,
                server_default='1',
                comment='How often (in DAYS) notifications are sent (1-15 days)'
            )
        )

    # Add username to clients (if not exists)
    if not column_exists('clients', 'username'):
        op.add_column(
            'clients',
            sa.Column(
                'username',
                sa.String(length=100),
                nullable=True,
                comment='Telegram username (without @)'
            )
        )


def downgrade() -> None:
    """Remove notification fields and username."""
    if column_exists('clients', 'username'):
        op.drop_column('clients', 'username')
    if column_exists('static_data', 'notification_period'):
        op.drop_column('static_data', 'notification_period')
    if column_exists('static_data', 'notification'):
        op.drop_column('static_data', 'notification')
