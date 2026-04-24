"""DAO for carousel_item_media — multi-media entries for feature items."""
from __future__ import annotations

import logging

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.models.carousel_item_media import CarouselItemMedia

logger = logging.getLogger(__name__)

# Per-item limits enforced before inserts.
MEDIA_LIMITS: dict[str, int] = {
    "image": 20,
    "gif":   20,
    "video":  5,
}


class CarouselItemMediaDAO:
    """Data Access Object for carousel_item_media entries."""

    @staticmethod
    async def create(
        session: AsyncSession,
        carousel_item_id: int,
        media_type: str,
        media_s3_key: str | None = None,
        media_url: str = "",
        order: int = 0,
    ) -> CarouselItemMedia:
        """Insert a single media entry and return it."""
        entry = CarouselItemMedia(
            carousel_item_id=carousel_item_id,
            media_type=media_type,
            media_s3_key=media_s3_key,
            media_url=media_url,
            order=order,
        )
        session.add(entry)
        await session.flush()
        await session.refresh(entry)
        return entry

    @staticmethod
    async def create_bulk(
        session: AsyncSession,
        carousel_item_id: int,
        entries: list[dict],
    ) -> list[CarouselItemMedia]:
        """
        Insert multiple media entries for a single carousel item.

        Each dict in ``entries`` must have:
          - ``media_type``: "image" | "gif" | "video"
          - ``media_s3_key`` (optional str)
          - ``media_url`` (optional str, default "")
          - ``order`` (optional int, default uses list position)
        """
        created: list[CarouselItemMedia] = []
        for idx, data in enumerate(entries):
            entry = CarouselItemMedia(
                carousel_item_id=carousel_item_id,
                media_type=data["media_type"],
                media_s3_key=data.get("media_s3_key"),
                media_url=data.get("media_url", ""),
                order=data.get("order", idx),
            )
            session.add(entry)
            created.append(entry)

        await session.flush()
        for entry in created:
            await session.refresh(entry)
        return created

    @staticmethod
    async def get_by_id(
        session: AsyncSession,
        media_id: int,
        carousel_item_id: int,
    ) -> CarouselItemMedia | None:
        """Fetch a single entry, scoped to its parent item (prevents IDOR)."""
        result = await session.execute(
            select(CarouselItemMedia).where(
                CarouselItemMedia.id == media_id,
                CarouselItemMedia.carousel_item_id == carousel_item_id,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_all_for_item(
        session: AsyncSession,
        carousel_item_id: int,
    ) -> list[CarouselItemMedia]:
        """Return all media entries for an item, ordered by ``order`` asc."""
        result = await session.execute(
            select(CarouselItemMedia)
            .where(CarouselItemMedia.carousel_item_id == carousel_item_id)
            .order_by(CarouselItemMedia.order.asc(), CarouselItemMedia.id.asc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def count_by_type(
        session: AsyncSession,
        carousel_item_id: int,
        media_type: str,
    ) -> int:
        """Count how many entries of a given type exist for the item."""
        from sqlalchemy import func

        result = await session.execute(
            select(func.count(CarouselItemMedia.id)).where(
                CarouselItemMedia.carousel_item_id == carousel_item_id,
                CarouselItemMedia.media_type == media_type,
            )
        )
        return result.scalar_one()

    @staticmethod
    async def delete_entry(
        session: AsyncSession,
        media_id: int,
        carousel_item_id: int,
    ) -> CarouselItemMedia | None:
        """
        Delete a single media entry and return it (so caller can clean up S3).

        Returns ``None`` if the entry doesn't exist or doesn't belong to the item.
        """
        entry = await CarouselItemMediaDAO.get_by_id(session, media_id, carousel_item_id)
        if entry is None:
            return None
        await session.delete(entry)
        await session.flush()
        return entry

    @staticmethod
    async def delete_all_for_item(
        session: AsyncSession,
        carousel_item_id: int,
    ) -> list[CarouselItemMedia]:
        """
        Delete all media entries for an item and return them for S3 cleanup.
        """
        entries = await CarouselItemMediaDAO.get_all_for_item(session, carousel_item_id)
        if entries:
            await session.execute(
                delete(CarouselItemMedia).where(
                    CarouselItemMedia.carousel_item_id == carousel_item_id
                )
            )
            await session.flush()
        return entries
