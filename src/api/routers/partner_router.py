"""Partner admin REST endpoints.

Prefix : ``/admin/partners``
RBAC   : ``partners:manage``

Routes:
    GET    /                                  → list partners
    GET    /{partner_id}                      → partner detail
    PATCH  /{partner_id}                      → update display_name / group_chat_id / is_active

    GET    /{partner_id}/payment-methods       → list cards + links
    POST   /{partner_id}/payment-methods       → create card or link
    PATCH  /{partner_id}/payment-methods/{id}  → update fields
    DELETE /{partner_id}/payment-methods/{id}  → remove

    GET    /{partner_id}/foto-hisobot          → fetch (auto-creates row)
    PUT    /{partner_id}/foto-hisobot          → replace text

    GET    /{partner_id}/aliases               → list flight masks
    PATCH  /{partner_id}/aliases/{alias_id}    → rename mask
    DELETE /{partner_id}/aliases/{alias_id}    → drop mask
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import AdminJWTPayload, get_db, require_permission
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
from src.api.services.partner_service import PartnerService

router = APIRouter(prefix="/admin/partners", tags=["Partners"])

_RequireManage = Depends(require_permission("partners", "manage"))


# ---------------------------------------------------------------------------
# Partner core
# ---------------------------------------------------------------------------


@router.get("", response_model=list[PartnerRead], dependencies=[_RequireManage])
async def list_partners(
    session: AsyncSession = Depends(get_db),
) -> list[PartnerRead]:
    return await PartnerService.list_partners(session)


@router.get(
    "/{partner_id}",
    response_model=PartnerRead,
    dependencies=[_RequireManage],
)
async def get_partner(
    partner_id: int,
    session: AsyncSession = Depends(get_db),
) -> PartnerRead:
    return await PartnerService.get_partner(session, partner_id)


@router.patch(
    "/{partner_id}",
    response_model=PartnerRead,
    dependencies=[_RequireManage],
)
async def update_partner(
    partner_id: int,
    body: PartnerUpdate,
    session: AsyncSession = Depends(get_db),
) -> PartnerRead:
    return await PartnerService.update_partner(session, partner_id, body)


# ---------------------------------------------------------------------------
# Payment methods
# ---------------------------------------------------------------------------


@router.get(
    "/{partner_id}/payment-methods",
    response_model=list[PaymentMethodRead],
    dependencies=[_RequireManage],
)
async def list_payment_methods(
    partner_id: int,
    only_active: bool = Query(default=False),
    session: AsyncSession = Depends(get_db),
) -> list[PaymentMethodRead]:
    return await PartnerService.list_payment_methods(
        session, partner_id, only_active=only_active
    )


@router.post(
    "/{partner_id}/payment-methods",
    response_model=PaymentMethodRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_RequireManage],
)
async def create_payment_method(
    partner_id: int,
    body: PaymentMethodCreate,
    session: AsyncSession = Depends(get_db),
) -> PaymentMethodRead:
    return await PartnerService.create_payment_method(session, partner_id, body)


@router.patch(
    "/{partner_id}/payment-methods/{method_id}",
    response_model=PaymentMethodRead,
    dependencies=[_RequireManage],
)
async def update_payment_method(
    partner_id: int,
    method_id: int,
    body: PaymentMethodUpdate,
    session: AsyncSession = Depends(get_db),
) -> PaymentMethodRead:
    return await PartnerService.update_payment_method(
        session, partner_id, method_id, body
    )


@router.delete(
    "/{partner_id}/payment-methods/{method_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    dependencies=[_RequireManage],
)
async def delete_payment_method(
    partner_id: int,
    method_id: int,
    session: AsyncSession = Depends(get_db),
) -> Response:
    await PartnerService.delete_payment_method(session, partner_id, method_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# foto_hisobot
# ---------------------------------------------------------------------------


@router.get(
    "/{partner_id}/foto-hisobot",
    response_model=PartnerFotoHisobotRead,
    dependencies=[_RequireManage],
)
async def get_foto_hisobot(
    partner_id: int,
    session: AsyncSession = Depends(get_db),
) -> PartnerFotoHisobotRead:
    return await PartnerService.get_foto_hisobot(session, partner_id)


@router.put(
    "/{partner_id}/foto-hisobot",
    response_model=PartnerFotoHisobotRead,
    dependencies=[_RequireManage],
)
async def update_foto_hisobot(
    partner_id: int,
    body: PartnerFotoHisobotUpdate,
    session: AsyncSession = Depends(get_db),
) -> PartnerFotoHisobotRead:
    return await PartnerService.update_foto_hisobot(session, partner_id, body)


# ---------------------------------------------------------------------------
# Flight aliases
# ---------------------------------------------------------------------------


@router.get(
    "/{partner_id}/aliases",
    response_model=list[FlightAliasRead],
    dependencies=[_RequireManage],
)
async def list_aliases(
    partner_id: int,
    limit: int = Query(default=100, ge=1, le=1000),
    session: AsyncSession = Depends(get_db),
) -> list[FlightAliasRead]:
    return await PartnerService.list_aliases(session, partner_id, limit=limit)


@router.patch(
    "/{partner_id}/aliases/{alias_id}",
    response_model=FlightAliasRead,
    dependencies=[_RequireManage],
)
async def update_alias(
    partner_id: int,
    alias_id: int,
    body: FlightAliasUpdate,
    session: AsyncSession = Depends(get_db),
) -> FlightAliasRead:
    return await PartnerService.update_alias(session, partner_id, alias_id, body)


@router.delete(
    "/{partner_id}/aliases/{alias_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    dependencies=[_RequireManage],
)
async def delete_alias(
    partner_id: int,
    alias_id: int,
    session: AsyncSession = Depends(get_db),
) -> Response:
    await PartnerService.delete_alias(session, partner_id, alias_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
