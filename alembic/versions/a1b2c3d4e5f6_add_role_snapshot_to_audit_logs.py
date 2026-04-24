"""add_role_snapshot_to_audit_logs

Revision ID: a1b2c3d4e5f6
Revises: 35161f60472f
Create Date: 2026-03-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '35161f60472f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add role_snapshot column to admin_audit_logs for historical context."""
    op.add_column(
        'admin_audit_logs',
        sa.Column('role_snapshot', sa.String(length=64), nullable=True),
    )
    op.create_index(
        'ix_admin_audit_logs_role_snapshot',
        'admin_audit_logs',
        ['role_snapshot'],
    )


def downgrade() -> None:
    """Remove role_snapshot column from admin_audit_logs."""
    op.drop_index('ix_admin_audit_logs_role_snapshot', table_name='admin_audit_logs')
    op.drop_column('admin_audit_logs', 'role_snapshot')
