"""China address Info"""

import os
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import FSInputFile, Message, InputMediaPhoto
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.filters.is_private_chat import IsPrivate
from src.bot.filters.is_logged_in import ClientExists, IsRegistered, IsLoggedIn
from src.infrastructure.services import ClientService


china_address_router = Router(name="china_address")


@china_address_router.message(
    IsPrivate(),
    ClientExists(),
    IsRegistered(),
    IsLoggedIn(),
    F.text.in_(["🇨🇳 Xitoy Manzili", "🇨🇳 Адрес в Китае"]),
)
async def china_address_handler(
    message: Message,
    _: callable,
    session: AsyncSession,
    client_service: ClientService,
    state: FSMContext,
):
    """Show China address information."""
    await state.clear()
    # Get client for client_code
    client = await client_service.get_client(message.from_user.id, session)

    if not client:
        await message.answer(_("error-occurred"))
        return

    # Get the path to the image files
    base_dir = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    )
    image_path_pindoudou = os.path.join(
        base_dir, "src", "assets", "images", "pindoudou_temp.jpg"
    )
    image_path_taobao = os.path.join(
        base_dir, "src", "assets", "images", "taobao_temp.jpg"
    )

    media = [
        InputMediaPhoto(
            media=FSInputFile(image_path_pindoudou),
            caption=(
                f"{client.primary_code} 18161955318\n"
                "陕西省咸阳市渭城区 北杜街道\n"
                f"昭容南街东航物流园内中京仓{client.primary_code}号仓库"
            ),
        ),
        InputMediaPhoto(
            media=FSInputFile(image_path_taobao)
            # Ikkinchi rasmga caption bermasangiz ham bo‘ladi
        ),
    ]

    await message.answer_media_group(media=media)
    await message.answer(_("china-address-warning"))
