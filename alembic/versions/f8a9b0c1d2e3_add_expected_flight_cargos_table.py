"""Add expected_flight_cargos table

Revision ID: f8a9b0c1d2e3
Revises: c4d5e6f7a8b9
Create Date: 2026-04-11 00:00:00.000000

Why: Replaces the legacy Google Sheets integration for tracking pre-arrival
cargo coming from China.  Each row is one tracking code assigned to a specific
client within a specific flight/shipment batch.  track_code is UNIQUE because
a given parcel can only belong to one client in one flight.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "f8a9b0c1d2e3"
down_revision: str = "c4d5e6f7a8b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "expected_flight_cargos",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "flight_name",
            sa.String(length=255),
            nullable=False,
            comment="Shipment batch / flight name, e.g. M123-2025",
        ),
        sa.Column(
            "client_code",
            sa.String(length=50),
            nullable=False,
            comment="Client code — matches Client.extra_code or Client.client_code",
        ),
        sa.Column(
            "track_code",
            sa.String(length=100),
            nullable=False,
            comment="Globally unique cargo tracking code",
        ),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("track_code"),
    )

    # Individual column indexes
    op.create_index(
        op.f("ix_expected_flight_cargos_flight_name"),
        "expected_flight_cargos",
        ["flight_name"],
        unique=False,
    )
    op.create_index(
        op.f("ix_expected_flight_cargos_client_code"),
        "expected_flight_cargos",
        ["client_code"],
        unique=False,
    )
    op.create_index(
        op.f("ix_expected_flight_cargos_track_code"),
        "expected_flight_cargos",
        ["track_code"],
        unique=False,
    )

    # Composite index for the most common query pattern: filter by flight + client
    op.create_index(
        "ix_expected_cargo_flight_client",
        "expected_flight_cargos",
        ["flight_name", "client_code"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_expected_cargo_flight_client",
        table_name="expected_flight_cargos",
    )
    op.drop_index(
        op.f("ix_expected_flight_cargos_track_code"),
        table_name="expected_flight_cargos",
    )
    op.drop_index(
        op.f("ix_expected_flight_cargos_client_code"),
        table_name="expected_flight_cargos",
    )
    op.drop_index(
        op.f("ix_expected_flight_cargos_flight_name"),
        table_name="expected_flight_cargos",
    )
    op.drop_table("expected_flight_cargos")
