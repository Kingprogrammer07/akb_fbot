"""add cargo_delivery_proofs table

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-04-01 00:00:00.000000

Why: Warehouse workers must provide photographic evidence and a delivery
method when marking cargo as taken-away.  This table stores those proof
records immutably so no evidence can be lost or altered after the fact.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: str = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None

_DELIVERY_METHODS = ("uzpost", "bts", "akb", "yandex")


def upgrade() -> None:
    op.create_table(
        "cargo_delivery_proofs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "transaction_id",
            sa.Integer,
            sa.ForeignKey("client_transaction_data.id", ondelete="CASCADE"),
            nullable=False,
            comment="The cargo transaction that was taken away",
        ),
        sa.Column(
            "delivery_method",
            sa.String(32),
            nullable=False,
            comment="uzpost | bts | akb | yandex",
        ),
        sa.Column(
            "photo_s3_keys",
            sa.JSON,
            nullable=False,
            server_default="[]",
            comment="JSON array of S3 object keys for proof photos",
        ),
        sa.Column(
            "marked_by_admin_id",
            sa.Integer,
            sa.ForeignKey("admin_accounts.id", ondelete="SET NULL"),
            nullable=True,
            comment="Admin who performed the take-away marking",
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        # Validation: only known delivery methods are accepted.
        sa.CheckConstraint(
            "delivery_method IN ('uzpost', 'bts', 'akb', 'yandex')",
            name="check_delivery_method_values",
        ),
    )
    op.create_index(
        "ix_cargo_delivery_proofs_transaction_id",
        "cargo_delivery_proofs",
        ["transaction_id"],
    )
    op.create_index(
        "ix_cargo_delivery_proofs_marked_by_admin_id",
        "cargo_delivery_proofs",
        ["marked_by_admin_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_cargo_delivery_proofs_marked_by_admin_id", table_name="cargo_delivery_proofs")
    op.drop_index("ix_cargo_delivery_proofs_transaction_id", table_name="cargo_delivery_proofs")
    op.drop_table("cargo_delivery_proofs")
