"""Add price_per_kg to static_data

Revision ID: d8f2a1b5c3e7
Revises: c9e7f1a4d3b8
Create Date: 2026-01-02 18:30:00.000000

NOTE: This migration is now idempotent - it safely checks if the column exists
before attempting to add it. The column may already exist from the table creation
migration if running on a fresh database.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd8f2a1b5c3e7'
down_revision: Union[str, None] = 'c9e7f1a4d3b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def column_exists(table_name: str, column_name: str) -> bool:
    """Check if a column exists in the given table."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def upgrade() -> None:
    """Add price_per_kg column to static_data table (idempotent).

    Safely skips if column already exists.
    """
    if column_exists('static_data', 'price_per_kg'):
        return

    op.add_column(
        'static_data',
        sa.Column(
            'price_per_kg',
            sa.Float(),
            nullable=False,
            server_default='9.5',
            comment='Price per kilogram (e.g., 9.2, 10.4)'
        )
    )

    # Update existing rows with default value
    op.execute(
        sa.text("UPDATE static_data SET price_per_kg = 9.5 WHERE price_per_kg IS NULL")
    )


def downgrade() -> None:
    """Remove price_per_kg column from static_data table."""
    if column_exists('static_data', 'price_per_kg'):
        op.drop_column('static_data', 'price_per_kg')
