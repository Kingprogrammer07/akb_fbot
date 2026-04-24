import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Form, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db, get_translator, get_admin_user
from src.infrastructure.database.models.client import Client
from src.api.utils.constants import UZBEKISTAN_REGIONS
from src.bot.bot_instance import bot
from src.config import config, BASE_DIR
from src.infrastructure.database.dao.client import ClientDAO
from src.infrastructure.database.dao.client_transaction import ClientTransactionDAO
from src.infrastructure.database.dao.delivery_request import DeliveryRequestDAO
from src.infrastructure.tools.datetime_utils import get_current_time

router = APIRouter(prefix="/delivery", tags=["delivery"])
logger = logging.getLogger(__name__)


@router.post("/admin-delivery-request")
async def create_admin_delivery_request(
    client_id: int = Form(...),
    admin_telegram_id: int = Form(...),
    delivery_type: str = Form(...),
    flight_names_json: str = Form(..., description="JSON string of flight names array"),
    full_name: str = Form(...),
    phone: str = Form(...),
    region: str = Form(...),
    district: str = Form(...),
    address: str = Form(...),
    wallet_used: float = Form(0.0),
    receipt_file: Optional[UploadFile] = File(None),
    session: AsyncSession = Depends(get_db),
    _: callable = Depends(get_translator),
    _admin: Client = Depends(get_admin_user),
):
    """
    Admin-initiated delivery request.

    Creates, auto-approves, and processes a delivery request on behalf of a client.
    Accepts multipart/form-data to support optional receipt file uploads (UZPOST).
    """
    # Parse flight names from JSON string
    try:
        flight_names = json.loads(flight_names_json)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid flight_names_json format")

    # 1. Get and Update Client Info
    client = await ClientDAO.get_by_id(session, client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    client.full_name = full_name
    client.phone = phone
    client.region = region
    client.district = district
    client.address = address
    await session.flush()

    # 2. Handle Receipt Upload (for UZPOST)
    receipt_file_id = None
    channel_key = f"{delivery_type.upper()}_DELIVERY_REQUEST_CHANNEL_ID"
    admin_channel_id = getattr(
        config.telegram, channel_key, config.telegram.TASDIQLASH_GROUP_ID
    )

    if delivery_type == "uzpost" and receipt_file:
        from aiogram.types import BufferedInputFile

        file_bytes = await receipt_file.read()
        tg_file = BufferedInputFile(file_bytes, filename=receipt_file.filename)

        try:
            msg = await bot.send_document(
                chat_id=admin_channel_id,
                document=tg_file,
                caption="Uzpost To'lov Cheki",
            )
            receipt_file_id = msg.document.file_id
        except Exception as e:
            logger.error(f"Failed to upload receipt to Telegram: {e}")
            raise HTTPException(
                status_code=500, detail="Failed to upload receipt image"
            )

    # 3. Wallet Deduction Logic (only for UZPOST)
    if delivery_type == "uzpost" and wallet_used > 0:
        if not flight_names:
            raise HTTPException(
                status_code=400, detail="Flight names required for wallet deduction"
            )

        primary_flight = flight_names[0]
        existing_tx = await ClientTransactionDAO.get_by_client_code_flight(
            session, client.active_codes, primary_flight
        )
        if existing_tx:
            current_pbd = float(existing_tx.payment_balance_difference or 0)
            existing_tx.payment_balance_difference = current_pbd - wallet_used
            await session.flush()

    # 4. Create Auto-Approved Delivery Request
    delivery_req = await DeliveryRequestDAO.create(
        session=session,
        client_id=client.id,
        client_code=client.client_code,
        telegram_id=client.telegram_id,
        delivery_type=delivery_type,
        flight_names=json.dumps(flight_names, ensure_ascii=False),
        full_name=full_name,
        phone=phone,
        region=region,
        address=address,
        prepayment_receipt_file_id=receipt_file_id,
    )

    delivery_req.status = "approved"
    delivery_req.processed_by_admin_id = admin_telegram_id
    delivery_req.processed_at = get_current_time()
    await session.flush()

    # 5. Mark Transactions as Taken Away (Check both client_code and extra_code)
    await ClientTransactionDAO.mark_as_taken_by_client_and_flights(
        session=session,
        client_codes=client.active_codes,
        flights=flight_names,
    )

    await session.commit()

    # 6. Translate region & district for Telegram message
    try:
        with open(
            BASE_DIR / "locales" / "district_uz.json", "r", encoding="utf-8"
        ) as f:
            district_uz = json.load(f).get("districts", {}).get(client.region, {})
    except Exception:
        district_uz = {}

    region_str = UZBEKISTAN_REGIONS.get(client.region, client.region)
    district_str = district_uz.get(client.district, client.district)
    full_region_string = f"{region_str}, {district_str}"

    # 7. Telegram Notifications
    try:
        await bot.send_message(
            chat_id=client.telegram_id, text=_("delivery-request-approved")
        )

        wallet_info = (
            f"\n💰 Hamyondan: {wallet_used:,.0f} so'm" if wallet_used > 0 else ""
        )
        receipt_info = f"\n📎 Chek: Ilova qilindi" if receipt_file_id else ""

        admin_msg = (
            f"✅ <b>YANGI YETKAZIB BERISH (Admin tomonidan)</b>\n\n"
            f"📦 <b>Xizmat turi:</b> {delivery_type.upper()}\n\n"
            f"👤 <b>Mijoz:</b> {client.full_name} ({client.client_code})\n"
            f"📱 <b>Tel:</b> {client.phone}\n"
            f"📍 <b>Manzil:</b> {full_region_string}, {client.address}\n"
            f"✈️ <b>Reyslar:</b> {', '.join(flight_names)}"
            f"{wallet_info}{receipt_info}"
        )

        await bot.send_message(
            chat_id=admin_channel_id, text=admin_msg, parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Error sending delivery notifications: {e}")

    return {"message": "Success", "delivery_request_id": delivery_req.id}
