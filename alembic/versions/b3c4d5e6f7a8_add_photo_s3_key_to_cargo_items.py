"""add photo_s3_key to cargo_items

Revision ID: b3c4d5e6f7a8
Revises: a7b8c9d0e1f2
Create Date: 2026-04-05 00:00:00.000000

Why: The China partner import API (POST /api/v1/shipment/create) allows
uploading a product photo.  The S3 object key is stored here so the image
can be retrieved later via a presigned URL without embedding the full URL
(which would change on bucket rename / region migration).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "b3c4d5e6f7a8"
down_revision: str = "a7b8c9d0e1f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cargo_items",
        sa.Column(
            "photo_s3_key",
            sa.String(1024),
            nullable=True,
            comment="S3 key for product image (china_import_image/); NULL if no photo",
        ),
    )


def downgrade() -> None:
    op.drop_column("cargo_items", "photo_s3_key")
