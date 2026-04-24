"""
Wallet API Router.

Exposes wallet operations (balance, cards, refund, debt) as REST endpoints.
Replicates logic from src/bot/handlers/user/wallet.py.
Critical: refund and debt endpoints send Telegram notifications with inline approval buttons.
"""
import logging
import secrets

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from sqlalchemy.ext.asyncio import AsyncSession
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.api.dependencies import get_db, get_current_user, get_translator
from src.api.schemas.wallet import (
    WalletBalanceResponse,
    PaymentReminderItem,
    CardResponse,
    CardListResponse,
    CardCreateRequest,
    CardCreateResponse,
    RefundRequest,
    MessageResponse,
)
from src.bot.bot_instance import bot
from src.config import config
from src.infrastructure.database.dao.client_transaction import ClientTransactionDAO
from src.infrastructure.database.dao.user_payment_card import UserPaymentCardDAO
from src.infrastructure.services.user_payment_card import UserPaymentCardService
from src.infrastructure.database.models.client import Client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/wallet", tags=["wallet"])

MIN_REFUND_AMOUNT = 5000
MAX_CARDS_PER_USER = 5


def mask_card_number(card_number: str) -> str:
    """Mask card number showing only last 4 digits."""
    if len(card_number) >= 4:
        return f"**** **** **** {card_number[-4:]}"
    return card_number


# ==================== 1. Balance ====================

@router.get(
    "/balance",
    response_model=WalletBalanceResponse,
    summary="Get wallet balance",
    description="Returns the user's wallet balance (positive = overpaid, negative = debt).",
)
async def get_balance(
    session: AsyncSession = Depends(get_db),
    current_user: Client = Depends(get_current_user),
    _: callable = Depends(get_translator),
):
    """Get wallet balance for the authenticated user."""
    if not current_user.client_code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User has no client code assigned",
        )

    # Get separated balances
    balances = await ClientTransactionDAO.get_wallet_balances(
        session, current_user.client_code
    )

    # Fetch partial payment reminders
    transactions = await ClientTransactionDAO.get_by_telegram_id(
        session, current_user.telegram_id
    )
    reminders = []

    for tx in transactions:
        if tx.payment_status == "partial" and (float(tx.remaining_amount or 0) > 0):
            deadline_str = (
                tx.payment_deadline.strftime("%Y-%m-%d %H:%M")
                if tx.payment_deadline
                else _("not-set")
            )
            reminders.append(
                PaymentReminderItem(
                    flight=tx.reys,
                    total=float(tx.total_amount) if tx.total_amount else float(tx.summa or 0),
                    paid=float(tx.paid_amount) if tx.paid_amount else 0.0,
                    remaining=float(tx.remaining_amount) if tx.remaining_amount else 0.0,
                    deadline=deadline_str,
                    is_partial=True,
                )
            )

    return WalletBalanceResponse(
        wallet_balance=balances["wallet_balance"],
        debt=balances["debt"],
        reminders=reminders,
        warning_text=_("payment-reminder-warning") if reminders else None,
    )


# ==================== 2. List Cards ====================

@router.get(
    "/cards",
    response_model=CardListResponse,
    summary="List user's payment cards",
    description="Returns all active payment cards with masked numbers.",
)
async def list_cards(
    session: AsyncSession = Depends(get_db),
    current_user: Client = Depends(get_current_user),
):
    """List all active payment cards for the authenticated user."""
    cards = await UserPaymentCardService.get_user_cards(
        current_user.telegram_id, session
    )

    card_responses = [
        CardResponse(
            id=card.id,
            masked_number=mask_card_number(card.card_number),
            holder_name=card.holder_name,
            is_active=card.is_active,
        )
        for card in cards
    ]

    return CardListResponse(cards=card_responses, count=len(card_responses))


# ==================== 3. Create Card ====================

@router.post(
    "/cards",
    response_model=CardCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a new payment card",
    description="Create a new payment card. Max 5 cards per user.",
)
async def create_card(
    body: CardCreateRequest,
    session: AsyncSession = Depends(get_db),
    current_user: Client = Depends(get_current_user),
    _: callable = Depends(get_translator),
):
    """Add a new payment card for the authenticated user."""
    telegram_id = current_user.telegram_id

    # Check card limit
    count = await UserPaymentCardDAO.count_active_by_telegram_id(session, telegram_id)
    if count >= MAX_CARDS_PER_USER:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Card limit reached ({MAX_CARDS_PER_USER})",
        )

    # Check duplicate
    exists = await UserPaymentCardDAO.check_duplicate(
        session, telegram_id, body.card_number
    )
    if exists:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This card is already added",
        )

    # Create
    card = await UserPaymentCardService.create_card(
        telegram_id, body.card_number, body.holder_name, session
    )
    await session.commit()

    return CardCreateResponse(
        message="Card added successfully",
        card=CardResponse(
            id=card.id,
            masked_number=mask_card_number(card.card_number),
            holder_name=card.holder_name,
            is_active=card.is_active,
        ),
    )


# ==================== 4. Delete Card ====================

@router.delete(
    "/cards/{card_id}",
    response_model=MessageResponse,
    summary="Delete a payment card",
    description="Soft-delete a payment card owned by the user.",
)
async def delete_card(
    card_id: int,
    session: AsyncSession = Depends(get_db),
    current_user: Client = Depends(get_current_user),
):
    """Delete a payment card by ID (ownership check)."""
    deleted = await UserPaymentCardService.delete_card(
        card_id, current_user.telegram_id, session
    )
    await session.commit()

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Card not found or not owned by user",
        )

    return MessageResponse(message="Card deleted successfully")


# ==================== 5. Request Refund ====================

@router.post(
    "/refund",
    response_model=MessageResponse,
    summary="Request a refund",
    description="Submit a refund request. Sends notification to admin channel with approval buttons.",
)
async def request_refund(
    body: RefundRequest,
    session: AsyncSession = Depends(get_db),
    current_user: Client = Depends(get_current_user),
):
    """
    Request a refund from wallet balance.

    - Validates amount against MIN_REFUND_AMOUNT and current balance.
    - If new_card is provided, creates it (if under limit and not duplicate).
    - Sends a Telegram message to REFUND_CHANNEL_ID with approve/reject buttons.
    """
    if not current_user.client_code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User has no client code assigned",
        )

    telegram_id = current_user.telegram_id

    # Get balances
    balances = await ClientTransactionDAO.get_wallet_balances(
        session, current_user.client_code
    )

    # Validate amount
    if body.amount < MIN_REFUND_AMOUNT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Minimum refund amount is {MIN_REFUND_AMOUNT:,.0f} UZS",
        )

    if body.amount > balances["wallet_balance"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Amount exceeds balance ({balances['wallet_balance']:,.0f} UZS)",
        )

    # Resolve card details
    card_number = ""
    holder_name = ""

    if body.card_id:
        # Use existing card
        card = await UserPaymentCardDAO.get_by_id(session, body.card_id)
        if not card or card.telegram_id != telegram_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Card not found or not owned by user",
            )
        card_number = card.card_number
        holder_name = card.holder_name or ""

    elif body.new_card:
        # Use new card
        card_number = body.new_card.card_number
        holder_name = body.new_card.holder_name

        # Optionally save the new card
        exists = await UserPaymentCardDAO.check_duplicate(
            session, telegram_id, card_number
        )
        if not exists:
            count = await UserPaymentCardDAO.count_active_by_telegram_id(
                session, telegram_id
            )
            if count < MAX_CARDS_PER_USER:
                await UserPaymentCardService.create_card(
                    telegram_id, card_number, holder_name, session
                )
                await session.commit()
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either card_id or new_card must be provided",
        )

    # Generate a cryptographically random request key for the admin callback button.
    # Previously used MD5(telegram_id + time()) — MD5 is broken and time() is
    # low-entropy, so we replace both with 4 bytes of OS-level randomness.
    request_key = secrets.token_hex(4)

    # Build admin notification text
    admin_text = (
        f"🔄 <b>Refund Request (API)</b>\n\n"
        f"👤 Client: <code>{current_user.client_code}</code>\n"
        f"📛 Name: {current_user.full_name or 'N/A'}\n"
        f"📞 Phone: {current_user.phone or 'N/A'}\n"
        f"🆔 Telegram ID: <code>{telegram_id}</code>\n"
        f"💰 Amount: <b>{body.amount:,.0f} UZS</b>\n"
        f"💳 Card: <code>{card_number}</code>\n"
        f"👤 Holder: {holder_name}"
    )

    # Build inline keyboard with approve/reject buttons
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Approve",
        callback_data=f"refund_approve:{telegram_id}:{request_key}",
    )
    builder.button(
        text="❌ Reject",
        callback_data=f"refund_reject:{telegram_id}",
    )
    builder.adjust(1)

    # Send to refund channel
    try:
        await bot.send_message(
            chat_id=config.telegram.REFUND_CHANNEL_ID,
            text=admin_text,
            reply_markup=builder.as_markup(),
        )
    except Exception as e:
        logger.error(f"Failed to send refund request to admin channel: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to send notification to admin channel",
        )

    return MessageResponse(message="Refund request submitted successfully")


# ==================== 6. Pay Debt ====================

@router.post(
    "/pay-debt",
    response_model=MessageResponse,
    summary="Submit debt payment receipt",
    description="Upload a receipt for debt payment. Sends notification to admin group with approval buttons.",
)
async def pay_debt(
    receipt: UploadFile = File(..., description="Payment receipt image or document"),
    session: AsyncSession = Depends(get_db),
    current_user: Client = Depends(get_current_user),
):
    """
    Submit a debt payment receipt.

    - Calculates debt from balance (must be negative).
    - Sends the receipt to DEBT_GROUP_ID with approve/reject buttons.
    - Supports both photo (image/*) and document uploads.
    """
    if not current_user.client_code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User has no client code assigned",
        )

    telegram_id = current_user.telegram_id

    # Get balances and check for debt
    balances = await ClientTransactionDAO.get_wallet_balances(
        session, current_user.client_code
    )

    if balances["debt"] >= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No debt found — balance is zero or positive",
        )

    debt = abs(balances["debt"])

    # Read file content
    file_content = await receipt.read()
    if not file_content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Empty file uploaded",
        )

    # Build admin notification text
    admin_text = (
        f"💸 <b>Debt Payment Receipt (API)</b>\n\n"
        f"👤 Client: <code>{current_user.client_code}</code>\n"
        f"📛 Name: {current_user.full_name or 'N/A'}\n"
        f"📞 Phone: {current_user.phone or 'N/A'}\n"
        f"🆔 Telegram ID: <code>{telegram_id}</code>\n"
        f"💰 Debt: <b>{debt:,.0f} UZS</b>"
    )

    # Build inline keyboard with approve/reject buttons
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Approve",
        callback_data=f"debt_approve:{telegram_id}:{current_user.client_code}",
    )
    builder.button(
        text="❌ Reject",
        callback_data=f"debt_reject:{telegram_id}",
    )
    builder.adjust(1)

    # Send to debt group
# Send to debt group
    try:
        from aiogram.types import BufferedInputFile
        
        content_type = receipt.content_type or ""
        input_file = BufferedInputFile(file_content, filename=receipt.filename or "receipt")

        if content_type.startswith("image/"):
            await bot.send_photo(
                chat_id=config.telegram.DEBT_GROUP_ID,
                photo=input_file,
                caption=admin_text,
                reply_markup=builder.as_markup(),
            )
        else:
            await bot.send_document(
                chat_id=config.telegram.DEBT_GROUP_ID,
                document=input_file,
                caption=admin_text,
                reply_markup=builder.as_markup(),
            )
    except Exception as e:
        logger.error(f"Failed to send debt receipt to admin group: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to send notification to admin group",
        )

    return MessageResponse(message="Debt payment receipt submitted successfully")
