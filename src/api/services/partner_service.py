"""Business-logic layer for the Partner admin API.

Sits between routers and the partner DAOs / FlightMaskService.  Handles:

* HTTP-friendly error translation (404 / 409 / 400).
* Cache invalidation: any partner mutation refreshes the in-process
  ``PartnerResolver`` so the bot picks up changes without a restart.
* Coordinated commits — DAOs flush within the session, the service
  decides when to commit.
"""
from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.partner import (
    FlightAliasRead,
    FlightAliasUpdate,
    PartnerFotoHisobotRead,
    PartnerFotoHisobotUpdate,
    PartnerRead,
    PartnerUpdate,
    PaymentMethodCreate,
    PaymentMethodRead,
    PaymentMethodUpdate,
)
from src.infrastructure.database.dao.partner import PartnerDAO
from src.infrastructure.database.dao.partner_flight_alias import (
    PartnerFlightAliasDAO,
)
from src.infrastructure.database.dao.partner_payment_method import (
    PartnerPaymentMethodDAO,
)
from src.infrastructure.database.dao.partner_static_data import (
    PartnerStaticDataDAO,
)
from src.infrastructure.services.flight_mask import (
    FlightMaskConflictError,
    FlightMaskError,
    FlightMaskService,
)
from src.infrastructure.services.partner_resolver import get_resolver


class PartnerService:
    """All endpoints in :mod:`api.routers.partner_router` dispatch here."""

    # ------------------------------------------------------------------
    # Partner core
    # ------------------------------------------------------------------

    @staticmethod
    async def list_partners(session: AsyncSession) -> list[PartnerRead]:
        partners = await PartnerDAO.get_all(session)
        return [PartnerRead.model_validate(p) for p in partners]

    @staticmethod
    async def get_partner(
        session: AsyncSession, partner_id: int
    ) -> PartnerRead:
        partner = await PartnerDAO.get_by_id(session, partner_id)
        if partner is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Partner {partner_id} not found",
            )
        return PartnerRead.model_validate(partner)

    @staticmethod
    async def update_partner(
        session: AsyncSession, partner_id: int, body: PartnerUpdate
    ) -> PartnerRead:
        partner = await PartnerDAO.get_by_id(session, partner_id)
        if partner is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Partner {partner_id} not found",
            )
        data = body.model_dump(exclude_unset=True)
        if data:
            await PartnerDAO.update(session, partner, data)
            await session.commit()
            # Refresh resolver cache so bot picks up the change immediately.
            await get_resolver().refresh(session)
        return PartnerRead.model_validate(partner)

    # ------------------------------------------------------------------
    # Payment methods
    # ------------------------------------------------------------------

    @staticmethod
    async def list_payment_methods(
        session: AsyncSession, partner_id: int, only_active: bool = False
    ) -> list[PaymentMethodRead]:
        await PartnerService._assert_partner_exists(session, partner_id)
        methods = await PartnerPaymentMethodDAO.list_for_partner(
            session, partner_id, only_active=only_active
        )
        return [PaymentMethodRead.model_validate(m) for m in methods]

    @staticmethod
    async def create_payment_method(
        session: AsyncSession, partner_id: int, body: PaymentMethodCreate
    ) -> PaymentMethodRead:
        await PartnerService._assert_partner_exists(session, partner_id)
        try:
            body.assert_consistent()
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc

        data = body.model_dump(exclude_unset=False)
        # HttpUrl → str so SQLAlchemy stores plain text.
        if data.get("link_url") is not None:
            data["link_url"] = str(data["link_url"])
        data["partner_id"] = partner_id

        method = await PartnerPaymentMethodDAO.create(session, data)
        await session.commit()
        return PaymentMethodRead.model_validate(method)

    @staticmethod
    async def update_payment_method(
        session: AsyncSession,
        partner_id: int,
        method_id: int,
        body: PaymentMethodUpdate,
    ) -> PaymentMethodRead:
        method = await PartnerPaymentMethodDAO.get_by_id(session, method_id)
        if method is None or method.partner_id != partner_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Payment method {method_id} not found for partner {partner_id}",
            )

        data = body.model_dump(exclude_unset=True)
        if data.get("link_url") is not None:
            data["link_url"] = str(data["link_url"])
        if data:
            await PartnerPaymentMethodDAO.update(session, method, data)
            await session.commit()
        return PaymentMethodRead.model_validate(method)

    @staticmethod
    async def delete_payment_method(
        session: AsyncSession, partner_id: int, method_id: int
    ) -> None:
        method = await PartnerPaymentMethodDAO.get_by_id(session, method_id)
        if method is None or method.partner_id != partner_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Payment method {method_id} not found for partner {partner_id}",
            )
        await PartnerPaymentMethodDAO.delete(session, method)
        await session.commit()

    # ------------------------------------------------------------------
    # foto_hisobot (per-partner)
    # ------------------------------------------------------------------

    @staticmethod
    async def get_foto_hisobot(
        session: AsyncSession, partner_id: int
    ) -> PartnerFotoHisobotRead:
        await PartnerService._assert_partner_exists(session, partner_id)
        record = await PartnerStaticDataDAO.get_or_create(session, partner_id)
        await session.commit()
        return PartnerFotoHisobotRead.model_validate(record)

    @staticmethod
    async def update_foto_hisobot(
        session: AsyncSession,
        partner_id: int,
        body: PartnerFotoHisobotUpdate,
    ) -> PartnerFotoHisobotRead:
        await PartnerService._assert_partner_exists(session, partner_id)
        record = await PartnerStaticDataDAO.update_foto_hisobot(
            session, partner_id, body.foto_hisobot
        )
        await session.commit()
        return PartnerFotoHisobotRead.model_validate(record)

    # ------------------------------------------------------------------
    # Flight aliases
    # ------------------------------------------------------------------

    @staticmethod
    async def list_aliases(
        session: AsyncSession, partner_id: int, limit: int | None = 100
    ) -> list[FlightAliasRead]:
        await PartnerService._assert_partner_exists(session, partner_id)
        aliases = await PartnerFlightAliasDAO.list_for_partner(
            session, partner_id, limit=limit
        )
        return [FlightAliasRead.model_validate(a) for a in aliases]

    @staticmethod
    async def update_alias(
        session: AsyncSession,
        partner_id: int,
        alias_id: int,
        body: FlightAliasUpdate,
    ) -> FlightAliasRead:
        alias = await PartnerFlightAliasDAO.get_by_id(session, alias_id)
        if alias is None or alias.partner_id != partner_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Alias {alias_id} not found for partner {partner_id}",
            )
        try:
            await FlightMaskService.set_mask(
                session,
                partner_id=partner_id,
                real_flight_name=alias.real_flight_name,
                new_mask=body.mask_flight_name,
            )
            await session.commit()
        except FlightMaskConflictError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc
        except FlightMaskError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc
        # Re-fetch to get the persisted state.
        refreshed = await PartnerFlightAliasDAO.get_by_id(session, alias_id)
        return FlightAliasRead.model_validate(refreshed)

    @staticmethod
    async def delete_alias(
        session: AsyncSession, partner_id: int, alias_id: int
    ) -> None:
        alias = await PartnerFlightAliasDAO.get_by_id(session, alias_id)
        if alias is None or alias.partner_id != partner_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Alias {alias_id} not found for partner {partner_id}",
            )
        await PartnerFlightAliasDAO.delete(session, alias)
        await session.commit()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def _assert_partner_exists(
        session: AsyncSession, partner_id: int
    ) -> None:
        partner = await PartnerDAO.get_by_id(session, partner_id)
        if partner is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Partner {partner_id} not found",
            )
