"""add legacy_code column to clients

Revision ID: q1w2e3r4t5y6
Revises: p7z8r9e0d1w2
Create Date: 2026-04-28 00:00:00.000000

legacy_code was assumed to exist by f3c591793b10 but was never explicitly
created by any migration on a fresh database.  This migration adds it
idempotently so fresh installs and existing installs both work.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "q1w2e3r4t5y6"
down_revision: Union[str, None] = "p7z8r9e0d1w2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    client_cols = {c["name"] for c in inspector.get_columns("clients")}

    if "legacy_code" not in client_cols:
        op.add_column(
            "clients",
            sa.Column("legacy_code", sa.String(length=20), nullable=True),
        )

    legacy_uq_exists = any(
        "legacy_code" in uq.get("column_names", [])
        for uq in inspector.get_unique_constraints("clients")
    )
    if not legacy_uq_exists:
        op.create_unique_constraint(
            "uq_clients_legacy_code", "clients", ["legacy_code"]
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    client_cols = {c["name"] for c in inspector.get_columns("clients")}

    existing_uqs = inspector.get_unique_constraints("clients")
    legacy_uq_exists = any(
        "legacy_code" in uq.get("column_names", []) for uq in existing_uqs
    )
    if legacy_uq_exists:
        op.drop_constraint("uq_clients_legacy_code", "clients", type_="unique")

    if "legacy_code" in client_cols:
        op.drop_column("clients", "legacy_code")
