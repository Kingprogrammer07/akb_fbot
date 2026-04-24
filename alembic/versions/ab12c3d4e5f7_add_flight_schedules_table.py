"""Add flight_schedules table

Revision ID: ab12c3d4e5f7
Revises: f8a9b0c1d2e3
Create Date: 2026-04-17 00:00:00.000000

Why: Gives ops managers a structured, database-backed calendar for tracking
planned, delayed, and arrived flights without touching raw cargo data.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "ab12c3d4e5f7"
down_revision: str = "f8a9b0c1d2e3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "flight_schedules",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "flight_name",
            sa.String(length=255),
            nullable=False,
            comment="Shipment batch identifier, e.g. M123-2025",
        ),
        sa.Column(
            "flight_date",
            sa.Date(),
            nullable=False,
            comment="Expected or actual flight date",
        ),
        sa.Column(
            "type",
            sa.String(length=20),
            nullable=False,
            comment="'avia' or 'aksiya'",
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="scheduled",
            comment="'scheduled', 'delayed', or 'arrived'",
        ),
        sa.Column(
            "notes",
            sa.Text(),
            nullable=True,
            comment="Optional manager notes",
        ),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.CheckConstraint(
            "type IN ('avia', 'aksiya')",
            name="ck_flight_schedule_type",
        ),
        sa.CheckConstraint(
            "status IN ('arrived', 'scheduled', 'delayed')",
            name="ck_flight_schedule_status",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        op.f("ix_flight_schedules_flight_name"),
        "flight_schedules",
        ["flight_name"],
        unique=False,
    )
    op.create_index(
        op.f("ix_flight_schedules_flight_date"),
        "flight_schedules",
        ["flight_date"],
        unique=False,
    )
    op.create_index(
        "ix_flight_schedule_date_status",
        "flight_schedules",
        ["flight_date", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_flight_schedule_date_status", table_name="flight_schedules")
    op.drop_index(
        op.f("ix_flight_schedules_flight_date"), table_name="flight_schedules"
    )
    op.drop_index(
        op.f("ix_flight_schedules_flight_name"), table_name="flight_schedules"
    )
    op.drop_table("flight_schedules")
