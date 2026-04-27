"""Payment service for processing payments."""

from typing import Optional, Literal
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.keyboards.user.reply_keyb.user_home_kyb import user_main_menu_kyb
from src.bot.utils.i18n import i18n
from src.infrastructure.database.dao.client_transaction import ClientTransactionDAO
from src.infrastructure.database.dao.client_payment_event import ClientPaymentEventDAO
from src.infrastructure.services.client import ClientService
from src.infrastructure.services.client_transaction import ClientTransactionService
from src.infrastructure.services.payment_allocation import PaymentAllocationService
from src.infrastructure.tools.datetime_utils import get_current_time, to_tashkent
from src.infrastructure.tools.money_utils import money
from src.bot.bot_instance import bot
from src.config import config

from src.api.schemas.payment import (
    ProcessPaymentRequest,
    ProcessExistingTransactionPaymentRequest,
    PaymentResult,
    ProcessPaymentResponse,
    NotificationStatus,
    PaymentEvent,
    PaymentEventListResponse,
)
from .utils import (
    get_cargo_details,
    validate_cargo_ownership,
    validate_paid_amount,
    calculate_payment_balance_difference,
)


class PaymentServiceError(Exception):
    """Custom exception for payment service errors."""

    def __init__(self, message: str, error_code: str, details: Optional[dict] = None):
        self.message = message
        self.error_code = error_code
        self.details = details
        super().__init__(message)


class PaymentService:
    """Service for payment processing operations."""

    @staticmethod
    async def create_payment_transaction(
        client_code: str,
        flight: str,
        cargo_id: int,
        paid_amount: float,
        payment_type: Literal["cash", "click", "payme", "card"],
        admin_id: int,
        session: AsyncSession,
        expected_amount: float,
        weight: float,
        telegram_id: int,
        use_balance: bool = False,
        allow_overpayment: bool = False,
        existing_tx=None,
        card_id: int | None = None,
    ) -> tuple:  # sourcery skip: low-code-quality
        """
        Centralized payment transaction creation logic with optional wallet deduction.

        NO WALLET_ADJ pseudo-transactions are created. Instead, wallet usage is
        reflected entirely through payment_balance_difference on the real transaction.

        Algorithm (when use_balance=True):
        1. wallet_balance = sum(payment_balance_difference) for client (>0 = credit)
        2. wallet_used = min(wallet_balance, expected_amount)
        3. cash_needed = expected_amount - wallet_used
        4. Create ONE real transaction:
           - summa/total_amount = expected_amount (original cargo cost)
           - paid_amount = cash actually paid by client
           - payment_balance_difference = cash_paid - expected_amount
             (This absorbs the wallet deduction: sum(pbd) decreases by expected - cash_paid,
              which equals wallet_used when cash_paid covers the rest exactly)

        Returns:
            Tuple of (transaction, payment_balance_difference, wallet_balance_before,
                      wallet_deducted, wallet_balance_after)
        """
        wallet_balance_before = 0.0
        wallet_deducted = 0.0
        wallet_balance_after = 0.0

        # Partial top-up: when an existing partial transaction is reused, the
        # remaining_amount is the basis for this payment (not full expected_amount),
        # and previously paid cash must be preserved cumulatively.
        is_partial_topup = (
            existing_tx is not None and existing_tx.payment_status == "partial"
        )
        if is_partial_topup:
            basis = float(existing_tx.remaining_amount or expected_amount)
            prev_paid = float(existing_tx.paid_amount or 0)
            prev_total = float(existing_tx.total_amount or expected_amount)
        else:
            basis = expected_amount
            prev_paid = 0.0
            prev_total = expected_amount

        # Handle wallet balance deduction if requested
        if use_balance:
            wallet_balance_before = await ClientTransactionDAO.sum_payment_balance_difference_by_client_code(
                session, client_code
            )
            if wallet_balance_before > 0:
                wallet_deducted = min(wallet_balance_before, basis)

        # Only cash (naqt) payments automatically mark cargo as taken away.
        # Card (terminal) payments are settled electronically — the client picks
        # up the cargo later, so is_taken_away must remain False until explicitly set.
        is_cash_or_card = payment_type == "cash"
        payment_type_db = payment_type
        # is_taken_away logic deferred until payment_status is known

        # Calculate how much the client still needs to pay in cash/online
        cash_needed = basis - wallet_deducted

        if cash_needed <= 0:
            # Wallet fully covers the payment — no cash changes hands.
            transaction_service = ClientTransactionService()
            new_tx = await transaction_service.create_transaction(
                telegram_id=telegram_id,
                client_code=client_code,
                qator_raqami=cargo_id,
                reys=flight,
                summa=money(prev_total),
                vazn=str(weight),
                payment_receipt_file_id=None,
                payment_type=payment_type_db,
                payment_status="paid",
                paid_amount=money(prev_paid),  # preserve previously collected cash
                total_amount=money(prev_total),
                remaining_amount=0.0,
                is_taken_away=is_cash_or_card,  # Wallet covers all ' Paid ' Cash/Card takes away
                taken_away_date=get_current_time() if is_cash_or_card else None,
                session=session,
                existing_tx=existing_tx,
            )
            await session.flush()

            # pbd = total cash paid - original total. For fresh: 0 - expected_amount.
            # For partial top-up: prev_paid - prev_total (residual debt absorbed by wallet).
            payment_balance_difference = money(prev_paid - prev_total)
            if hasattr(new_tx, "payment_balance_difference"):
                new_tx.payment_balance_difference = payment_balance_difference

            # Wallet-only payment: always create a payment event so the cashier log
            # records every transaction regardless of payment method.
            await ClientPaymentEventDAO.create(
                session=session,
                transaction_id=new_tx.id,
                payment_provider="wallet",
                amount=float(wallet_deducted),
                approved_by_admin_id=admin_id,
                payment_card_id=None,
            )

            await session.flush()

            wallet_balance_after = await ClientTransactionDAO.sum_payment_balance_difference_by_client_code(
                session, client_code
            )

            return (
                new_tx,
                payment_balance_difference,
                wallet_balance_before,
                wallet_deducted,
                wallet_balance_after,
            )

        # Wallet doesn't fully cover — client must pay cash_needed.
        # allow_overpayment=True (used by the POS bulk endpoint) skips the
        # upper-bound guard so the cashier can accept any denomination bill;
        # the surplus automatically becomes a wallet credit via
        # payment_balance_difference = paid_amount - expected_amount.
        if allow_overpayment:
            if paid_amount <= 0:
                raise PaymentServiceError(
                    message="paid_amount must be greater than 0",
                    error_code="INVALID_PAID_AMOUNT",
                )
        else:
            is_valid, error_msg = validate_paid_amount(paid_amount, cash_needed)
            if not is_valid:
                raise PaymentServiceError(
                    message=error_msg,
                    error_code="INVALID_PAID_AMOUNT",
                )

        remaining_amount = max(0.0, cash_needed - paid_amount)
        payment_status = "paid" if remaining_amount <= 0 else "partial"

        # Cumulative paid_amount across all events for this transaction (preserves
        # previously collected cash on partial top-ups).
        new_paid_total = prev_paid + paid_amount

        # Golden Rule: Cash/Card + Paid = Taken Away
        should_take_away = is_cash_or_card and payment_status == "paid"

        transaction_service = ClientTransactionService()
        new_tx = await transaction_service.create_transaction(
            telegram_id=telegram_id,
            client_code=client_code,
            qator_raqami=cargo_id,
            reys=flight,
            summa=money(prev_total),
            vazn=str(weight),
            payment_receipt_file_id=None,
            payment_type=payment_type_db,
            payment_status=payment_status,
            paid_amount=money(new_paid_total),
            total_amount=money(prev_total),
            remaining_amount=money(remaining_amount),
            is_taken_away=should_take_away,
            taken_away_date=get_current_time() if should_take_away else None,
            session=session,
            existing_tx=existing_tx,
        )
        await session.flush()

        # pbd = total cash paid - original total. Sum(pbd) absorbs wallet usage.
        payment_balance_difference = money(new_paid_total - prev_total)
        if hasattr(new_tx, "payment_balance_difference"):
            new_tx.payment_balance_difference = payment_balance_difference

        await ClientPaymentEventDAO.create(
            session=session,
            transaction_id=new_tx.id,
            amount=paid_amount,
            approved_by_admin_id=admin_id,
            payment_provider=payment_type,
            payment_card_id=card_id,
        )

        await session.flush()

        if use_balance and wallet_deducted > 0:
            wallet_balance_after = await ClientTransactionDAO.sum_payment_balance_difference_by_client_code(
                session, client_code
            )

        return (
            new_tx,
            payment_balance_difference,
            wallet_balance_before,
            wallet_deducted,
            wallet_balance_after,
        )

    @staticmethod
    async def process_unpaid_cargo_payment(
        request: ProcessPaymentRequest, session: AsyncSession, translator: callable
    ) -> ProcessPaymentResponse:
        """
        Process payment for unpaid cargo (new transaction).

        Creates a new ClientTransaction and ClientPaymentEvent.
        For cash payments: marks cargo as taken immediately.
        For online/card payments: cargo remains not taken.

        REQUIRED: paid_amount must be provided in request.
        """
        # Get client
        client_service = ClientService()
        client = await client_service.get_client_by_code(request.client_code, session)
        if not client:
            raise PaymentServiceError(
                message="Client not found", error_code="CLIENT_NOT_FOUND"
            )

        # Get cargo data
        cargo_data = await get_cargo_details(request.cargo_id, session)
        if not cargo_data:
            raise PaymentServiceError(
                message="Cargo not found", error_code="CARGO_NOT_FOUND"
            )

        # Validate cargo ownership
        is_valid, error_msg = validate_cargo_ownership(
            cargo_data, request.client_code, request.flight, client
        )
        if not is_valid:
            raise PaymentServiceError(
                message=error_msg, error_code="CARGO_VALIDATION_FAILED"
            )

        # Check for duplicate transaction (exact cargo row match first)
        existing_tx = await ClientTransactionDAO.get_by_client_code_flight_row(
            session, client.active_codes, request.flight, request.cargo_id
        )
        if existing_tx and existing_tx.payment_status in ("paid", "partial"):
            raise PaymentServiceError(
                message="Payment already exists or partially paid for this cargo",
                error_code="PAYMENT_EXISTS",
                details={"transaction_id": existing_tx.id},
            )

        # Fallback: pending-debt row (qator_raqami=0) written by bulk_cargo_sender.
        # Re-use it instead of inserting a second transaction for the same user+flight.
        if not existing_tx:
            pending_debt_tx = await ClientTransactionDAO.get_by_client_code_flight_row(
                session, client.active_codes, request.flight, 0
            )
            if pending_debt_tx and pending_debt_tx.payment_status == "pending":
                existing_tx = pending_debt_tx

        expected_amount = cargo_data["total_amount"]
        weight = cargo_data["weight"]
        telegram_id = client.telegram_id or 0

        # Canonical code: agar pending-debt (yoki boshqa mavjud) qator bor bo'lsa —
        # uning client_code sini qayta ishlatamiz, aks holda cargo.client_id (raw
        # kelgan kod). Shunda bulk_cargo_sender qaysi kod bilan yozgan bo'lsa,
        # biz ham shu kod bilan update qilamiz — dublikat bo'lmaydi.
        if existing_tx and existing_tx.client_code:
            canonical_code = existing_tx.client_code
        else:
            canonical_code = cargo_data.get("client_id") or client.payment_code

        try:
            result = await PaymentService.create_payment_transaction(
                client_code=canonical_code,
                flight=request.flight,
                cargo_id=request.cargo_id,
                paid_amount=request.paid_amount,
                payment_type=request.payment_type,
                admin_id=request.admin_id,
                session=session,
                expected_amount=expected_amount,
                weight=weight,
                telegram_id=telegram_id,
                use_balance=request.use_balance,
                existing_tx=existing_tx,
            )

            (
                new_tx,
                payment_balance_difference,
                wallet_balance_before,
                wallet_deducted,
                wallet_balance_after,
            ) = result

            await session.commit()

            is_cash = request.payment_type == "cash"

            notification_status = await PaymentService._send_payment_notifications(
                client=client,
                transaction_id=new_tx.id,
                flight=request.flight,
                amount=request.paid_amount,
                payment_type=request.payment_type,
                admin_id=request.admin_id,
                is_cash=is_cash,
                translator=translator,
                wallet_deducted=wallet_deducted if request.use_balance else None,
            )

            return ProcessPaymentResponse(
                payment=PaymentResult(
                    success=True,
                    transaction_id=new_tx.id,
                    client_code=request.client_code,
                    flight=request.flight,
                    expected_amount=float(expected_amount),
                    paid_amount=float(request.paid_amount),
                    payment_balance_difference=payment_balance_difference,
                    payment_type=request.payment_type,
                    payment_status=new_tx.payment_status,
                    is_taken_away=new_tx.is_taken_away,
                    message="Payment processed successfully",
                    created_at=new_tx.created_at,
                    wallet_balance_before=wallet_balance_before
                    if request.use_balance
                    else None,
                    wallet_deducted=wallet_deducted if request.use_balance else None,
                    wallet_balance_after=wallet_balance_after
                    if request.use_balance
                    else None,
                    track_codes=None,
                ),
                notifications=notification_status,
            )

        except PaymentServiceError:
            await session.rollback()
            raise
        except Exception as e:
            await session.rollback()
            raise PaymentServiceError(
                message=f"Payment processing failed: {str(e)}",
                error_code="PROCESSING_FAILED",
            ) from e

    @staticmethod
    async def process_existing_transaction_payment(
        request: ProcessExistingTransactionPaymentRequest,
        session: AsyncSession,
        translator: callable,
    ) -> ProcessPaymentResponse:    # sourcery skip: low-code-quality
        """
        Process payment for existing transaction (partial payments).

        Wallet deduction is handled by adjusting payment_balance_difference
        directly on the existing transaction -- no WALLET_ADJ rows created.
        """
        # Get transaction
        transaction = await ClientTransactionDAO.get_by_id(
            session, request.transaction_id
        )
        if not transaction:
            raise PaymentServiceError(
                message="Transaction not found", error_code="TRANSACTION_NOT_FOUND"
            )

        if transaction.is_taken_away:
            raise PaymentServiceError(
                message="Cargo already taken", error_code="CARGO_ALREADY_TAKEN"
            )

        # Get client
        client_service = ClientService()
        client = await client_service.get_client_by_code(
            transaction.client_code, session
        )
        if not client:
            raise PaymentServiceError(
                message="Client not found", error_code="CLIENT_NOT_FOUND"
            )

        expected_amount = float(transaction.total_amount or transaction.summa or 0)

        wallet_balance_before = 0.0
        wallet_deducted = 0.0
        wallet_balance_after = 0.0
        remaining_to_pay = float(transaction.remaining_amount or expected_amount)

        # Handle wallet balance deduction if requested
        if request.use_balance:
            wallet_balance_before = await ClientTransactionDAO.sum_payment_balance_difference_by_client_code(
                session, transaction.client_code
            )

            if wallet_balance_before > 0:
                wallet_deducted = min(wallet_balance_before, remaining_to_pay)
                remaining_to_pay -= wallet_deducted

        # Validate paid_amount against remaining expected amount
        if remaining_to_pay > 0:
            is_valid, error_msg = validate_paid_amount(
                request.paid_amount, remaining_to_pay
            )
            if not is_valid:
                raise PaymentServiceError(
                    message=error_msg, error_code="INVALID_PAID_AMOUNT"
                )

        is_cash = request.payment_type == "cash"
        payment_type_db = request.payment_type

        try:
            if request.paid_amount > 0:
                await ClientPaymentEventDAO.create(
                    session=session,
                    transaction_id=transaction.id,
                    amount=request.paid_amount,
                    approved_by_admin_id=request.admin_id,
                    payment_provider=request.payment_type,
                )

            # If only wallet was used (paid_amount == 0), record the wallet
            # deduction as a separate event so it appears in the payment history.
            # Without this, wallet-only payments on existing transactions would
            # be invisible in the payment events log.
            if wallet_deducted > 0 and request.paid_amount == 0:
                await ClientPaymentEventDAO.create(
                    session=session,
                    transaction_id=transaction.id,
                    amount=wallet_deducted,
                    approved_by_admin_id=request.admin_id,
                    payment_provider="wallet",
                )

            # Recalculate base balance from events
            await PaymentAllocationService.recalculate_transaction_balance(
                session, transaction.id
            )
            await session.refresh(transaction)

            total_paid = float(transaction.paid_amount or 0)
            # Update remaining amount considering wallet deduction
            effective_total_paid = total_paid + wallet_deducted
            if transaction.total_amount:
                transaction.remaining_amount = money(
                    max(0.0, float(transaction.total_amount) - effective_total_paid)
                )
            else:
                transaction.remaining_amount = 0.0

            # payment_balance_difference = cash_paid - expected (wallet absorbed via sum(pbd))
            # When wallet is used, we adjust pbd to account for wallet deduction
            payment_balance_difference = money(total_paid - expected_amount)
            if hasattr(transaction, "payment_balance_difference"):
                transaction.payment_balance_difference = payment_balance_difference

            # Update payment status
            if transaction.remaining_amount <= 0:
                transaction.payment_status = "paid"
                transaction.remaining_amount = 0.0
                if not transaction.fully_paid_date:
                    transaction.fully_paid_date = get_current_time()
            else:
                transaction.payment_status = "partial"

            # For cash/card payments, mark as taken ONLY if fully paid
            if (
                request.payment_type in ("cash", "card")
                and transaction.payment_status == "paid"
            ):
                transaction.is_taken_away = True
                transaction.taken_away_date = get_current_time()

            await session.commit()

            # Get final wallet balance
            if request.use_balance and wallet_deducted > 0:
                wallet_balance_after = await ClientTransactionDAO.sum_payment_balance_difference_by_client_code(
                    session, transaction.client_code
                )

            notification_status = await PaymentService._send_payment_notifications(
                client=client,
                transaction_id=transaction.id,
                flight=transaction.reys or "Unknown",
                amount=request.paid_amount,
                payment_type=request.payment_type,
                admin_id=request.admin_id,
                is_cash=is_cash,
                translator=translator,
                wallet_deducted=wallet_deducted if request.use_balance else None,
            )

            return ProcessPaymentResponse(
                payment=PaymentResult(
                    success=True,
                    transaction_id=transaction.id,
                    client_code=transaction.client_code,
                    flight=transaction.reys or "Unknown",
                    expected_amount=expected_amount,
                    paid_amount=float(request.paid_amount),
                    payment_balance_difference=payment_balance_difference,
                    payment_type=request.payment_type,
                    payment_status=transaction.payment_status,
                    is_taken_away=transaction.is_taken_away,
                    message="Payment processed successfully",
                    created_at=transaction.created_at,
                    wallet_balance_before=wallet_balance_before
                    if request.use_balance
                    else None,
                    wallet_deducted=wallet_deducted if request.use_balance else None,
                    wallet_balance_after=wallet_balance_after
                    if request.use_balance
                    else None,
                    track_codes=None,
                ),
                notifications=notification_status,
            )

        except PaymentServiceError:
            await session.rollback()
            raise
        except Exception as e:
            await session.rollback()
            raise PaymentServiceError(
                message=f"Payment processing failed: {str(e)}",
                error_code="PROCESSING_FAILED",
            ) from e

    @staticmethod
    async def mark_transaction_taken(
        transaction_id: int,
        admin_id: int,
        role_snapshot: str,
        session: AsyncSession,
    ) -> dict:
        """
        Mark a transaction's cargo as taken by the client.

        Payment status does NOT block this action — an admin can release cargo
        regardless of whether it has been fully paid, partially paid, or not
        paid at all.  This covers edge cases such as:
          • Client picks up and pays later (pending → taken).
          • Debt has been negotiated offline (partial → taken).

        For partial transactions, the workflow is force-closed (payment_status
        set to "paid", remaining_amount zeroed) while the debt is preserved
        unchanged in payment_balance_difference.

        For pending transactions, payment_status is intentionally left as
        "pending" so debt/balance calculations remain accurate.

        Every successful call flushes an immutable AdminAuditLog entry
        (action="MARK_CARGO_TAKEN") inside the same transaction, so the
        commit either persists both the state change and the audit record,
        or neither (no phantom log entries on failure).

        Args:
            transaction_id: PK of the ClientTransaction row.
            admin_id:        Admin DB PK from the JWT payload.
            role_snapshot:   Role name at action time (immutable audit context).
            session:         Async DB session — committed inside this method.

        Returns:
            Dict with success flag and final transaction state.

        Raises:
            PaymentServiceError: TRANSACTION_NOT_FOUND or ALREADY_TAKEN.
        """
        from src.infrastructure.database.dao.admin_audit_log import AdminAuditLogDAO

        transaction = await ClientTransactionDAO.get_by_id(session, transaction_id)
        if not transaction:
            raise PaymentServiceError(
                message="Transaction not found",
                error_code="TRANSACTION_NOT_FOUND",
            )

        if transaction.is_taken_away:
            raise PaymentServiceError(
                message="Cargo already marked as taken",
                error_code="ALREADY_TAKEN",
            )

        original_payment_status = transaction.payment_status

        # Force-close partial transactions: close the workflow but preserve debt.
        # CRITICAL: Do NOT touch payment_balance_difference — it stays negative
        # (e.g. -5000) to track what the client still owes.
        if transaction.payment_status == "partial":
            transaction.payment_status = "paid"
            transaction.remaining_amount = 0
            transaction.payment_deadline = None
            if not transaction.fully_paid_date:
                transaction.fully_paid_date = get_current_time()

        # Pending (never-paid) transactions are allowed through as-is.
        # payment_status stays "pending" so debt tracking is unaffected.

        transaction.is_taken_away = True
        transaction.taken_away_date = get_current_time()

        # Flush the audit record inside the same transaction so the mark-taken
        # state change and its audit trail are always committed together.
        await AdminAuditLogDAO.log(
            session=session,
            action="MARK_CARGO_TAKEN",
            admin_id=admin_id,
            role_snapshot=role_snapshot,
            details={
                "transaction_id": transaction_id,
                "client_code": transaction.client_code,
                "flight": transaction.reys,
                "original_payment_status": original_payment_status,
                "final_payment_status": transaction.payment_status,
                "payment_balance_difference": float(
                    transaction.payment_balance_difference or 0
                ),
            },
        )

        await session.commit()

        return {
            "success": True,
            "transaction_id": transaction_id,
            "is_taken_away": True,
            "taken_away_date": transaction.taken_away_date,
            "payment_status": transaction.payment_status,
            "payment_balance_difference": float(
                transaction.payment_balance_difference or 0
            ),
        }

    @staticmethod
    async def get_payment_events(
        transaction_id: int, session: AsyncSession
    ) -> PaymentEventListResponse:
        """Get all payment events for a transaction."""
        events_raw = await ClientPaymentEventDAO.get_by_transaction_id(
            session, transaction_id
        )

        events = [
            PaymentEvent(
                id=event.id,
                transaction_id=event.transaction_id,
                amount=float(event.amount),
                payment_provider=event.payment_provider,
                approved_by_admin_id=event.approved_by_admin_id,
                created_at=event.created_at,
            )
            for event in events_raw
        ]

        total_paid = await ClientPaymentEventDAO.get_total_paid_by_transaction_id(
            session, transaction_id
        )

        breakdown = await ClientPaymentEventDAO.get_payment_breakdown_by_transaction_id(
            session, transaction_id
        )

        return PaymentEventListResponse(
            events=events, total_paid=total_paid, payment_breakdown=breakdown
        )

    @staticmethod
    async def _send_payment_notifications(
        client,
        transaction_id: int,
        flight: str,
        amount: float,
        payment_type: str,
        admin_id: int,
        is_cash: bool,
        translator: callable,
        wallet_deducted: float = None,
    ) -> NotificationStatus:
        """Send payment notifications to user and channel."""
        status = NotificationStatus()
        telegram_id = client.telegram_id

        # Create user-localized translator based on client's language preference
        user_lang = client.language_code if client and client.language_code else "uz"

        def user_text(key, **kwargs):
            return i18n.get(user_lang, key, **kwargs)

        # When paid_amount=0, the full cargo cost was covered by the wallet.
        # Use wallet_deducted as the display total so notifications show the real
        # cargo amount instead of "0 so'm", which would confuse the client.
        display_amount = (
            wallet_deducted if (amount == 0 and wallet_deducted) else amount
        )

        # Notify user (For ALL payment types - Click, Payme, Card, Cash)
        if telegram_id:
            try:
                # Select message key based on payment type
                msg_key = (
                    "payment-cash-confirmed-user"
                    if is_cash
                    else "payment-online-confirmed-user"
                )

                # Format payment type for display (e.g., "Click", "Payme")
                provider_name = payment_type.title() if payment_type else "Online"

                user_message = user_text(
                    msg_key, amount=f"{display_amount:,.0f}", payment_type=provider_name
                )

                # Append wallet deduction info if applicable
                if wallet_deducted and wallet_deducted > 0:
                    wallet_msg = user_text(
                        "wallet-deducted-notice", amount=f"{wallet_deducted:,.0f}"
                    )
                    # Fallback if key not exists
                    if "wallet-deducted-notice" in wallet_msg:
                        wallet_msg = (
                            f"💰 Hamyondan: {wallet_deducted:,.0f} so'm ayirildi"
                        )
                    user_message += f"\n\n{wallet_msg}"

                await bot.send_message(
                    chat_id=telegram_id,
                    text=user_message,
                    reply_markup=user_main_menu_kyb(translator=user_text),
                )
                status.user_notified = True
            except Exception as e:
                status.user_notification_error = str(e)

        # Send to channel with enhanced details
        channel_id = config.telegram.TOLOV_TASDIQLANGAN_CHANNEL_ID
        try:
            current_time = get_current_time()
            tashkent_time = to_tashkent(current_time)
            formatted_time = tashkent_time.strftime("%Y-%m-%d %H:%M:%S")

            # Bug 3 fix: use primary_code (canonical identifier) so the notification
            # always shows the code the client actually goes by, not just the raw
            # client_code DB column which may be null or superseded by extra_code.
            canonical_code = client.primary_code
            if is_cash:
                channel_text = (
                    f"✅ <b>Naqd to'lov tasdiqlandi</b>\n\n"
                    f"👤 Mijoz: <code>{canonical_code}</code>\n"
                    f"✈️ Reys: {flight}\n"
                    f"💰 Summa: {display_amount:,.0f} so'm\n"
                )
            else:
                provider_map = {"click": "Click", "payme": "Payme", "card": "Karta"}
                provider_display = provider_map.get(payment_type, payment_type.title())
                channel_text = (
                    f"✅ <b>{provider_display} to'lov tasdiqlandi</b>\n\n"
                    f"👤 Mijoz: <code>{canonical_code}</code>\n"
                    f"✈️ Reys: {flight}\n"
                    f"💰 Summa: {display_amount:,.0f} so'm\n"
                )

            if wallet_deducted and wallet_deducted > 0:
                channel_text += f"💳 Hamyondan: {wallet_deducted:,.0f} so'm\n"

            channel_text += (
                f"📱 Telefon: {client.phone or 'N/A'}\n"
                f"🆔 Telegram ID: {telegram_id or 'N/A'}\n"
                f"🔢 Tranzaksiya: #{transaction_id}\n"
                f"👨‍💼 Admin: #{admin_id}\n"
                f"🕐 Vaqt: {formatted_time}"
            )

            await bot.send_message(
                chat_id=channel_id, text=channel_text, parse_mode="HTML"
            )
            status.channel_notified = True
        except Exception as e:
            status.channel_notification_error = str(e)

        return status
