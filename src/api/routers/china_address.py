"""
China Address API Router.

Returns the authenticated client's personal China warehouse address
with structured fields for easy frontend rendering.
"""
import logging

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db, get_current_user, get_translator
from src.api.schemas.china_address import ChinaAddressResponse
from src.infrastructure.database.models.client import Client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/clients/me", tags=["clients"])

CHINA_PHONE = "18161955318"
CHINA_REGION = "陕西省咸阳市渭城区 北杜街道"
CHINA_ADDRESS_TEMPLATE = "昭容南街东航物流园内中京仓{code}号仓库"

IMAGE_FILENAMES = [
    "pindoudou_temp.jpg",
    "taobao_temp.jpg",
]


@router.get(
    "/china-address",
    response_model=ChinaAddressResponse,
    summary="Get China warehouse address",
    description="Returns the client's personalised China warehouse address with instructional images.",
)
async def get_china_address(
    request: Request,
    session: AsyncSession = Depends(get_db),
    current_user: Client = Depends(get_current_user),
    _: callable = Depends(get_translator),
):
    code = current_user.extra_code or current_user.client_code
    address_line = CHINA_ADDRESS_TEMPLATE.format(code=code)
    full_address = f"{code} {CHINA_PHONE}\n{CHINA_REGION}\n{address_line}"

    base_url = str(request.base_url).rstrip("/")
    images = [f"{base_url}/static/images/{name}" for name in IMAGE_FILENAMES]

    return ChinaAddressResponse(
        client_code=code,
        phone=CHINA_PHONE,
        region=CHINA_REGION,
        address_line=address_line,
        full_address_string=full_address,
        warning_text=_("china-address-warning"),
        images=images,
    )
