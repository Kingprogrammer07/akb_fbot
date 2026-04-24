"""Live calculator endpoint for cargo cost estimation."""
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from redis.asyncio import Redis

from src.api.dependencies import get_admin_from_jwt, get_db, get_redis, get_current_user
from src.api.schemas.calculator import CalculatorRequest, CalculatorResponse
from src.infrastructure.database.dao.static_data import StaticDataDAO
from src.infrastructure.database.models.client import Client
from src.bot.utils.currency_cache import convert_to_uzs

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["calculator"])


@router.post(
    "/calculator",
    response_model=CalculatorResponse,
    summary="Live cargo cost calculator",
    description="Calculate estimated shipping cost based on weight and optional dimensions.",
)
async def calculate_cost(
    body: CalculatorRequest,
    session: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    admin=Depends(get_admin_from_jwt),
) -> CalculatorResponse:
    # 1. Determine chargeable weight
    if body.is_gabarit:
        volumetric_weight = body.x * body.y * body.z * 167  # type: ignore[operator]
        chargeable_weight = max(volumetric_weight, body.m)
    else:
        chargeable_weight = body.m

    # 2. Fetch price_per_kg from static_data
    static_data = await StaticDataDAO.get_by_id(session, 1)
    if not static_data or static_data.price_per_kg is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Pricing configuration not found",
        )

    price_per_kg_usd: float = static_data.price_per_kg

    # 3. Calculate USD price
    estimated_price_usd = chargeable_weight * price_per_kg_usd

    # 4. Convert to UZS using existing currency cache utility
    estimated_price_uzs = await convert_to_uzs(estimated_price_usd, redis, session)
    price_per_kg_uzs = await convert_to_uzs(price_per_kg_usd, redis, session)

    return CalculatorResponse(
        chargeable_weight=round(chargeable_weight, 2),
        price_per_kg_usd=round(price_per_kg_usd, 2),
        price_per_kg_uzs=round(price_per_kg_uzs, 0),
        estimated_price_usd=round(estimated_price_usd, 2),
        estimated_price_uzs=round(estimated_price_uzs, 0),
    )
