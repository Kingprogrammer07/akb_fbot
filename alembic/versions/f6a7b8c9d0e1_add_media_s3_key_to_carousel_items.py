"""add media_s3_key to carousel_items

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-04-05 00:00:00.000000

Why: Carousel items now support direct S3 uploads from the admin panel.
The s3_key is stored so old files can be cleaned up when an item is
updated or deleted (avoids orphaned S3 objects).
NULL means the media_url is an external link, not an S3-managed file.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "f6a7b8c9d0e1"
down_revision: str = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "carousel_items",
        sa.Column(
            "media_s3_key",
            sa.String(1024),
            nullable=True,
            comment="S3 object key (set when media was uploaded via API)",
        ),
    )


def downgrade() -> None:
    op.drop_column("carousel_items", "media_s3_key")
