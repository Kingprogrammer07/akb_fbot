"""Create session_logs table.

Revision ID: create_session_logs_table
Revises: 
Create Date: 2026-02-03 14:32:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'create_session_logs_table'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'session_logs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('client_id', sa.Integer(), nullable=False),
        sa.Column('telegram_id', sa.BigInteger(), nullable=False),
        sa.Column('event_type', sa.String(length=20), nullable=False),
        sa.Column('ip_address', sa.String(length=50), nullable=True),
        sa.Column('device_info', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    # Create indexes
    op.create_index('ix_session_logs_client_id', 'session_logs', ['client_id'], unique=False)
    op.create_index('ix_session_logs_client_created', 'session_logs', ['client_id', 'created_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_session_logs_client_created', table_name='session_logs')
    op.drop_index('ix_session_logs_client_id', table_name='session_logs')
    op.drop_table('session_logs')
