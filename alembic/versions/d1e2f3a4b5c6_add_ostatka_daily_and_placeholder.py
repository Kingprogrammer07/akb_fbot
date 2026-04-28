"""add ostatka_daily_notifications + expected_flight_cargos.is_placeholder

Revision ID: d1e2f3a4b5c6
Revises: c0d1e2f3a4b5
Create Date: 2026-04-24 10:30:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "d1e2f3a4b5c6"
down_revision: str = "c0d1e2f3a4b5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    op.add_column(
        "static_data",
        sa.Column(
            "ostatka_daily_notifications",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
            comment="Whether to post daily ostatka (A-) leftover statistics to group",
        ),
    )

    if "expected_flight_cargos" in existing_tables:
        existing_cols = {c["name"] for c in inspector.get_columns("expected_flight_cargos")}
        if "is_placeholder" not in existing_cols:
            op.add_column(
                "expected_flight_cargos",
                sa.Column(
                    "is_placeholder",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.false(),
                    comment="Placeholder row used to register an empty flight without any track codes",
                ),
            )
        existing_indexes = {ix['name'] for ix in inspector.get_indexes("expected_flight_cargos")}
        if "ix_expected_cargo_placeholder" not in existing_indexes:
            op.create_index(
                "ix_expected_cargo_placeholder",
                "expected_flight_cargos",
                ["is_placeholder"],
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "expected_flight_cargos" in existing_tables:
        existing_indexes = {ix['name'] for ix in inspector.get_indexes("expected_flight_cargos")}
        if "ix_expected_cargo_placeholder" in existing_indexes:
            op.drop_index(
                "ix_expected_cargo_placeholder",
                table_name="expected_flight_cargos",
            )
        existing_cols = {c["name"] for c in inspector.get_columns("expected_flight_cargos")}
        if "is_placeholder" in existing_cols:
            op.drop_column("expected_flight_cargos", "is_placeholder")
    op.drop_column("static_data", "ostatka_daily_notifications")
