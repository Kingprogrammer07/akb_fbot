"""Add price_per_kg to flight_cargos

Revision ID: c9e7f1a4d3b8
Revises: a7f4c8d3e2b9
Create Date: 2026-01-02 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c9e7f1a4d3b8'
down_revision: Union[str, None] = 'a7f4c8d3e2b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add price_per_kg column to flight_cargos table."""
    op.add_column(
        'flight_cargos',
        sa.Column(
            'price_per_kg',
            sa.Numeric(precision=10, scale=2),
            nullable=True,
            comment='Price per kilogram (e.g., 9.2, 10.4)'
        )
    )


def downgrade() -> None:
    """Remove price_per_kg column from flight_cargos table."""
    op.drop_column('flight_cargos', 'price_per_kg')
