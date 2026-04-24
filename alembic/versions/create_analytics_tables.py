"""Create analytics_events and api_request_logs tables

Revision ID: create_analytics_tables
Revises: add_updated_at_to_payment_events
Create Date: 2026-01-22 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'create_analytics_tables'
down_revision: Union[str, None] = 'add_updated_at_to_payment_events'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create analytics_events and api_request_logs tables."""
    
    # Create analytics_events table
    op.create_table(
        'analytics_events',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            'event_type',
            sa.String(length=100),
            nullable=False,
            comment="Type of event (e.g., 'client_registration', 'cargo_upload')"
        ),
        sa.Column(
            'user_id',
            sa.BigInteger(),
            nullable=True,
            comment='Telegram ID of user who triggered the event (no FK to avoid blocking writes)'
        ),
        sa.Column(
            'event_data',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment='Flexible JSON payload with event-specific data'
        ),
        sa.Column(
            'created_at',
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text('CURRENT_TIMESTAMP'),
            comment='Timestamp when event was created'
        ),
        sa.Column(
            'updated_at',
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text('CURRENT_TIMESTAMP'),
            comment='Timestamp when event was last updated'
        ),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create indexes for analytics_events
    op.create_index(
        'ix_analytics_events_event_type',
        'analytics_events',
        ['event_type']
    )
    op.create_index(
        'ix_analytics_events_user_id',
        'analytics_events',
        ['user_id']
    )
    op.create_index(
        'ix_analytics_events_event_type_created_at',
        'analytics_events',
        ['event_type', 'created_at']
    )
    op.create_index(
        'ix_analytics_events_user_id_created_at',
        'analytics_events',
        ['user_id', 'created_at']
    )
    
    # Create api_request_logs table
    op.create_table(
        'api_request_logs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            'method',
            sa.String(length=10),
            nullable=False,
            comment='HTTP method (GET, POST, PUT, DELETE, etc.)'
        ),
        sa.Column(
            'endpoint',
            sa.String(length=512),
            nullable=False,
            comment='API endpoint path'
        ),
        sa.Column(
            'user_id',
            sa.BigInteger(),
            nullable=True,
            comment='Telegram ID of authenticated user (no FK to avoid blocking writes)'
        ),
        sa.Column(
            'response_status',
            sa.Integer(),
            nullable=False,
            comment='HTTP response status code'
        ),
        sa.Column(
            'response_time_ms',
            sa.Integer(),
            nullable=False,
            comment='Request processing time in milliseconds'
        ),
        sa.Column(
            'error_message',
            sa.Text(),
            nullable=True,
            comment='Error message if request failed (null for successful requests)'
        ),
        sa.Column(
            'ip_address',
            sa.String(length=45),
            nullable=True,
            comment='Client IP address'
        ),
        sa.Column(
            'created_at',
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text('CURRENT_TIMESTAMP'),
            comment='Timestamp when request was logged'
        ),
        sa.Column(
            'updated_at',
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text('CURRENT_TIMESTAMP'),
            comment='Timestamp when log was last updated'
        ),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create indexes for api_request_logs
    op.create_index(
        'ix_api_request_logs_method',
        'api_request_logs',
        ['method']
    )
    op.create_index(
        'ix_api_request_logs_endpoint',
        'api_request_logs',
        ['endpoint']
    )
    op.create_index(
        'ix_api_request_logs_user_id',
        'api_request_logs',
        ['user_id']
    )
    op.create_index(
        'ix_api_request_logs_response_status',
        'api_request_logs',
        ['response_status']
    )
    op.create_index(
        'ix_api_request_logs_endpoint_created_at',
        'api_request_logs',
        ['endpoint', 'created_at']
    )
    op.create_index(
        'ix_api_request_logs_response_status_created_at',
        'api_request_logs',
        ['response_status', 'created_at']
    )
    op.create_index(
        'ix_api_request_logs_user_id_created_at',
        'api_request_logs',
        ['user_id', 'created_at']
    )


def downgrade() -> None:
    """Drop analytics_events and api_request_logs tables."""
    # Drop indexes for api_request_logs
    op.drop_index('ix_api_request_logs_user_id_created_at', table_name='api_request_logs')
    op.drop_index('ix_api_request_logs_response_status_created_at', table_name='api_request_logs')
    op.drop_index('ix_api_request_logs_endpoint_created_at', table_name='api_request_logs')
    op.drop_index('ix_api_request_logs_response_status', table_name='api_request_logs')
    op.drop_index('ix_api_request_logs_user_id', table_name='api_request_logs')
    op.drop_index('ix_api_request_logs_endpoint', table_name='api_request_logs')
    op.drop_index('ix_api_request_logs_method', table_name='api_request_logs')
    
    # Drop api_request_logs table
    op.drop_table('api_request_logs')
    
    # Drop indexes for analytics_events
    op.drop_index('ix_analytics_events_user_id_created_at', table_name='analytics_events')
    op.drop_index('ix_analytics_events_event_type_created_at', table_name='analytics_events')
    op.drop_index('ix_analytics_events_user_id', table_name='analytics_events')
    op.drop_index('ix_analytics_events_event_type', table_name='analytics_events')
    
    # Drop analytics_events table
    op.drop_table('analytics_events')

