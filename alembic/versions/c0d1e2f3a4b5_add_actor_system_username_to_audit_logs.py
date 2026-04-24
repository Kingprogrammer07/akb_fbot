"""add actor_system_username to admin audit logs

Revision ID: c0d1e2f3a4b5
Revises: b9c0d1e2f3a4
Create Date: 2026-04-24 10:05:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "c0d1e2f3a4b5"
down_revision: str = "b9c0d1e2f3a4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "admin_audit_logs",
        sa.Column(
            "actor_system_username",
            sa.String(length=64),
            nullable=True,
            comment="Immutable snapshot of the acting admin's system username",
        ),
    )


def downgrade() -> None:
    op.drop_column("admin_audit_logs", "actor_system_username")
