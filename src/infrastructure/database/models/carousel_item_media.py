"""Media entries for feature-type carousel items (multi-media support)."""
from sqlalchemy import ForeignKey, Integer, String, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.infrastructure.database.models.base import Base


class CarouselItemMedia(Base):
    """
    A single media attachment belonging to a 'feature' carousel item.

    One CarouselItem can have up to:
      - 20 images
      -  5 videos
      - 20 GIFs

    The ``media_url`` column stores an external URL directly.
    The ``media_s3_key`` column stores the S3 object key; ``media_url``
    is left empty and a presigned URL is generated at read time.
    Exactly one of the two must be populated (enforced in application code).
    """

    __tablename__ = "carousel_item_media"

    carousel_item_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("carousel_items.id", ondelete="CASCADE"),
        nullable=False,
        comment="FK → carousel_items.id",
    )
    media_s3_key: Mapped[str | None] = mapped_column(
        String(1024),
        nullable=True,
        comment="S3 object key; NULL for external-URL entries",
    )
    media_url: Mapped[str] = mapped_column(
        String(1024),
        nullable=False,
        default="",
        comment="External URL (empty when media_s3_key is set)",
    )
    media_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="image | gif | video",
    )
    order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Display order within the item (ascending)",
    )

    __table_args__ = (
        CheckConstraint(
            "media_type IN ('image', 'gif', 'video')",
            name="chk_carousel_item_media_type",
        ),
    )

    # Back-reference populated by CarouselItem.media_items relationship.
    item: Mapped["CarouselItem"] = relationship(  # type: ignore[name-defined]
        "CarouselItem",
        back_populates="media_items",
    )

    def __repr__(self) -> str:
        return (
            f"<CarouselItemMedia(id={self.id}, "
            f"item_id={self.carousel_item_id}, "
            f"type={self.media_type}, order={self.order})>"
        )
