"""DAO for CargoDeliveryProof — warehouse take-away evidence records."""
from typing import Sequence

from sqlalchemy import delete, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.infrastructure.database.dao.base import BaseDAO
from src.infrastructure.database.models.cargo_delivery_proof import CargoDeliveryProof


class CargoDeliveryProofDAO(BaseDAO[CargoDeliveryProof]):
    """Thin async DAO around CargoDeliveryProof."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(CargoDeliveryProof, session)

    @staticmethod
    async def create(
        session: AsyncSession,
        transaction_id: int,
        delivery_method: str,
        photo_s3_keys: list[str],
        marked_by_admin_id: int | None,
    ) -> CargoDeliveryProof:
        """
        Persist a new delivery proof record and flush (caller must commit).

        Args:
            transaction_id:     FK to the cargo transaction row.
            delivery_method:    One of: uzpost, bts, akb, yandex.
            photo_s3_keys:      List of S3 object keys for the proof photos.
            marked_by_admin_id: Admin who performed the action (nullable).
        """
        proof = CargoDeliveryProof(
            transaction_id=transaction_id,
            delivery_method=delivery_method,
            photo_s3_keys=photo_s3_keys,
            marked_by_admin_id=marked_by_admin_id,
        )
        session.add(proof)
        await session.flush()
        return proof

    @staticmethod
    async def get_by_transaction_id(
        session: AsyncSession,
        transaction_id: int,
    ) -> Sequence[CargoDeliveryProof]:
        """Return all proof records for a given transaction, newest first."""
        result = await session.execute(
            select(CargoDeliveryProof)
            .where(CargoDeliveryProof.transaction_id == transaction_id)
            .order_by(CargoDeliveryProof.created_at.desc())
        )
        return result.scalars().all()

    @staticmethod
    async def get_by_admin_id_paginated(
        session: AsyncSession,
        admin_id: int,
        limit: int = 20,
        offset: int = 0,
    ) -> Sequence[CargoDeliveryProof]:
        """
        Return paginated proof records created by the given admin, newest first.

        Eagerly loads ``transaction`` so the router can read ``reys``,
        ``client_code``, and financial fields without extra queries.
        """
        result = await session.execute(
            select(CargoDeliveryProof)
            .where(CargoDeliveryProof.marked_by_admin_id == admin_id)
            .options(selectinload(CargoDeliveryProof.transaction))
            .order_by(CargoDeliveryProof.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return result.scalars().all()

    @staticmethod
    async def count_by_admin_id(
        session: AsyncSession,
        admin_id: int,
    ) -> int:
        """Count proof records created by the given admin."""
        result = await session.execute(
            select(func.count(CargoDeliveryProof.id))
            .where(CargoDeliveryProof.marked_by_admin_id == admin_id)
        )
        return result.scalar_one()

    @staticmethod
    async def get_proven_transaction_ids(
        session: AsyncSession,
        transaction_ids: list[int],
    ) -> set[int]:
        """Return the subset of given transaction_ids that have at least one proof record."""
        if not transaction_ids:
            return set()
        result = await session.execute(
            select(distinct(CargoDeliveryProof.transaction_id))
            .where(CargoDeliveryProof.transaction_id.in_(transaction_ids))
        )
        return set(result.scalars().all())

    @staticmethod
    async def delete_by_transaction_id(
        session: AsyncSession,
        transaction_id: int,
    ) -> int:
        """Delete all proof rows for a transaction. Returns number of rows deleted."""
        result = await session.execute(
            delete(CargoDeliveryProof)
            .where(CargoDeliveryProof.transaction_id == transaction_id)
        )
        await session.flush()
        return result.rowcount or 0


    @staticmethod
    async def exists_for_transaction(
        session: AsyncSession,
        transaction_id: int,
    ) -> bool:
        """Return True if at least one proof record exists for this transaction."""
        result = await session.execute(
            select(func.count(CargoDeliveryProof.id))
            .where(CargoDeliveryProof.transaction_id == transaction_id)
        )
        return result.scalar_one() > 0
