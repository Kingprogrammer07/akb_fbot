"""Create statistics aggregation tables

Revision ID: create_stats_aggregation_tables
Revises: create_analytics_tables
Create Date: 2026-01-22 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'create_stats_aggregation_tables'
down_revision: Union[str, None] = 'create_analytics_tables'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create stats_daily_clients, stats_daily_cargo, and stats_daily_payments tables."""
    
    # Create stats_daily_clients table
    op.create_table(
        'stats_daily_clients',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            'stat_date',
            sa.Date(),
            nullable=False,
            comment="Date for which statistics are aggregated (YYYY-MM-DD)"
        ),
        sa.Column(
            'registrations_count',
            sa.Integer(),
            nullable=False,
            server_default='0',
            comment='Number of new client registrations'
        ),
        sa.Column(
            'approvals_count',
            sa.Integer(),
            nullable=False,
            server_default='0',
            comment='Number of client approvals'
        ),
        sa.Column(
            'logins_count',
            sa.Integer(),
            nullable=False,
            server_default='0',
            comment='Number of client logins'
        ),
        sa.Column(
            'active_clients_count',
            sa.Integer(),
            nullable=False,
            server_default='0',
            comment='Total number of active clients (with client_code) as of this date'
        ),
        sa.Column(
            'created_at',
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text('CURRENT_TIMESTAMP'),
            comment='Timestamp when stat was created'
        ),
        sa.Column(
            'updated_at',
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text('CURRENT_TIMESTAMP'),
            comment='Timestamp when stat was last updated'
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('stat_date', name='uq_stats_daily_clients_date')
    )
    
    # Create indexes for stats_daily_clients
    op.create_index('ix_stats_daily_clients_stat_date', 'stats_daily_clients', ['stat_date'])
    
    # Create stats_daily_cargo table
    op.create_table(
        'stats_daily_cargo',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            'stat_date',
            sa.Date(),
            nullable=False,
            comment="Date for which statistics are aggregated (YYYY-MM-DD)"
        ),
        sa.Column(
            'flight_name',
            sa.String(length=100),
            nullable=True,
            comment="Flight name (null for overall daily stats, or specific flight)"
        ),
        sa.Column(
            'uploads_count',
            sa.Integer(),
            nullable=False,
            server_default='0',
            comment='Number of cargo photo uploads'
        ),
        sa.Column(
            'unique_clients_count',
            sa.Integer(),
            nullable=False,
            server_default='0',
            comment='Number of unique clients who uploaded cargo'
        ),
        sa.Column(
            'total_photos_count',
            sa.Integer(),
            nullable=False,
            server_default='0',
            comment='Total number of photos uploaded'
        ),
        sa.Column(
            'total_weight_kg',
            sa.Numeric(precision=12, scale=2),
            nullable=True,
            comment='Total weight of all cargo in kilograms'
        ),
        sa.Column(
            'avg_weight_kg',
            sa.Numeric(precision=12, scale=2),
            nullable=True,
            comment='Average weight per cargo item in kilograms'
        ),
        sa.Column(
            'created_at',
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text('CURRENT_TIMESTAMP'),
            comment='Timestamp when stat was created'
        ),
        sa.Column(
            'updated_at',
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text('CURRENT_TIMESTAMP'),
            comment='Timestamp when stat was last updated'
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('stat_date', 'flight_name', name='uq_stats_daily_cargo_date_flight')
    )
    
    # Create indexes for stats_daily_cargo
    op.create_index('ix_stats_daily_cargo_stat_date', 'stats_daily_cargo', ['stat_date'])
    op.create_index('ix_stats_daily_cargo_flight_name', 'stats_daily_cargo', ['flight_name'])
    op.create_index('ix_stats_daily_cargo_stat_date_flight', 'stats_daily_cargo', ['stat_date', 'flight_name'])
    
    # Create stats_daily_payments table
    op.create_table(
        'stats_daily_payments',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            'stat_date',
            sa.Date(),
            nullable=False,
            comment="Date for which statistics are aggregated (YYYY-MM-DD)"
        ),
        sa.Column(
            'payment_type',
            sa.String(length=10),
            nullable=True,
            comment="Payment type: 'online' or 'cash' (null for overall stats)"
        ),
        sa.Column(
            'approvals_count',
            sa.Integer(),
            nullable=False,
            server_default='0',
            comment='Number of payment approvals'
        ),
        sa.Column(
            'total_amount',
            sa.Numeric(precision=15, scale=2),
            nullable=False,
            server_default='0',
            comment='Total amount of payments approved in UZS'
        ),
        sa.Column(
            'full_payments_count',
            sa.Integer(),
            nullable=False,
            server_default='0',
            comment='Number of full payment approvals'
        ),
        sa.Column(
            'partial_payments_count',
            sa.Integer(),
            nullable=False,
            server_default='0',
            comment='Number of partial payment approvals'
        ),
        sa.Column(
            'full_payments_amount',
            sa.Numeric(precision=15, scale=2),
            nullable=False,
            server_default='0',
            comment='Total amount from full payments in UZS'
        ),
        sa.Column(
            'partial_payments_amount',
            sa.Numeric(precision=15, scale=2),
            nullable=False,
            server_default='0',
            comment='Total amount from partial payments in UZS'
        ),
        sa.Column(
            'avg_amount',
            sa.Numeric(precision=15, scale=2),
            nullable=True,
            comment='Average payment amount in UZS'
        ),
        sa.Column(
            'created_at',
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text('CURRENT_TIMESTAMP'),
            comment='Timestamp when stat was created'
        ),
        sa.Column(
            'updated_at',
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text('CURRENT_TIMESTAMP'),
            comment='Timestamp when stat was last updated'
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('stat_date', 'payment_type', name='uq_stats_daily_payments_date_type')
    )
    
    # Create indexes for stats_daily_payments
    op.create_index('ix_stats_daily_payments_stat_date', 'stats_daily_payments', ['stat_date'])
    op.create_index('ix_stats_daily_payments_payment_type', 'stats_daily_payments', ['payment_type'])
    op.create_index('ix_stats_daily_payments_stat_date_type', 'stats_daily_payments', ['stat_date', 'payment_type'])


def downgrade() -> None:
    """Drop statistics aggregation tables."""
    op.drop_index('ix_stats_daily_payments_stat_date_type', table_name='stats_daily_payments')
    op.drop_index('ix_stats_daily_payments_payment_type', table_name='stats_daily_payments')
    op.drop_index('ix_stats_daily_payments_stat_date', table_name='stats_daily_payments')
    op.drop_table('stats_daily_payments')
    
    op.drop_index('ix_stats_daily_cargo_stat_date_flight', table_name='stats_daily_cargo')
    op.drop_index('ix_stats_daily_cargo_flight_name', table_name='stats_daily_cargo')
    op.drop_index('ix_stats_daily_cargo_stat_date', table_name='stats_daily_cargo')
    op.drop_table('stats_daily_cargo')
    
    op.drop_index('ix_stats_daily_clients_stat_date', table_name='stats_daily_clients')
    op.drop_table('stats_daily_clients')

