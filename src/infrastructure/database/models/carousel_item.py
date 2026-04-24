"""Carousel item model for ads/features management."""
from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import String, Boolean, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.infrastructure.database.models.base import Base

if TYPE_CHECKING:
    from src.infrastructure.database.models.carousel_item_media import CarouselItemMedia


class CarouselItem(Base):
    """
    Carousel item for displaying ads and features in the WebApp.
    
    Types:
    - 'ad': Advertisement banners
    - 'feature': Feature highlights
    
    Media types:
    - 'image': Static image
    - 'video': Video content
    - 'gif': Animated GIF
    """
    
    __tablename__ = "carousel_items"

    type: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="Item type: 'ad' or 'feature'"
    )
    title: Mapped[str | None] = mapped_column(
        String(256), nullable=True, comment="Display title"
    )
    sub_title: Mapped[str | None] = mapped_column(
        String(512), nullable=True, comment="Display subtitle"
    )
    media_type: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="Media type: 'image', 'video', or 'gif'"
    )
    media_url: Mapped[str] = mapped_column(
        String(1024), nullable=False, comment="URL to the media file"
    )
    # S3 object key for media uploaded via the admin upload endpoint.
    # NULL for items whose media_url is an external link.
    # Populated by the upload endpoint; used to clean up S3 on update/delete.
    media_s3_key: Mapped[str | None] = mapped_column(
        String(1024), nullable=True, comment="S3 object key (set when media was uploaded via API)"
    )
    action_url: Mapped[str | None] = mapped_column(
        String(1024), nullable=True, comment="URL to open when item is clicked"
    )
    text_color: Mapped[str] = mapped_column(
        String(20), nullable=False, default="#ffffff", comment="Text color hex code"
    )
    gradient: Mapped[str | None] = mapped_column(
        String(512), nullable=True, comment="CSS gradient string (for features)"
    )
    order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="Display order (ascending)"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, comment="Whether the item is visible"
    )

    # Only populated for 'feature' type items; empty list for 'ad' items.
    media_items: Mapped[list[CarouselItemMedia]] = relationship(
        "CarouselItemMedia",
        back_populates="item",
        cascade="all, delete-orphan",
        order_by="CarouselItemMedia.order",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<CarouselItem(id={self.id}, type={self.type}, title={self.title}, active={self.is_active})>"
