"""Wallet API schemas."""
from typing import Optional, List
from pydantic import BaseModel, Field, field_validator


# ==================== Responses ====================

class PaymentReminderItem(BaseModel):
    flight: str
    total: float
    paid: float
    remaining: float
    deadline: str
    is_partial: bool = True


class WalletBalanceResponse(BaseModel):
    """Wallet balance response."""
    wallet_balance: float = Field(..., description="Available positive balance")
    debt: float = Field(..., description="Total debt amount (negative)")
    currency: str = "UZS"
    reminders: List[PaymentReminderItem] = Field(default_factory=list)
    warning_text: Optional[str] = None


class CardResponse(BaseModel):
    """User payment card response (masked)."""
    id: int
    masked_number: str = Field(..., description="Masked card number, e.g. **** **** **** 1234")
    holder_name: Optional[str] = None
    is_active: bool = True

    class Config:
        from_attributes = True


class CardListResponse(BaseModel):
    """List of user payment cards."""
    cards: list[CardResponse]
    count: int


class CardCreateResponse(BaseModel):
    """Response after creating a card."""
    success: bool = True
    message: str
    card: CardResponse


class MessageResponse(BaseModel):
    """Generic message response."""
    success: bool = True
    message: str


# ==================== Requests ====================

class CardCreateRequest(BaseModel):
    """Request to create a new payment card."""
    card_number: str = Field(..., min_length=16, max_length=16, description="16-digit card number")
    holder_name: str = Field(..., min_length=2, max_length=255, description="Card holder name")

    @field_validator("card_number")
    @classmethod
    def validate_card_number(cls, v: str) -> str:
        cleaned = v.strip().replace(" ", "").replace("-", "")
        if not cleaned.isdigit() or len(cleaned) != 16:
            raise ValueError("Card number must be exactly 16 digits")
        return cleaned


class NewCardInput(BaseModel):
    """New card details for inline creation during refund."""
    card_number: str = Field(..., min_length=16, max_length=16)
    holder_name: str = Field(..., min_length=2, max_length=255)

    @field_validator("card_number")
    @classmethod
    def validate_card_number(cls, v: str) -> str:
        cleaned = v.strip().replace(" ", "").replace("-", "")
        if not cleaned.isdigit() or len(cleaned) != 16:
            raise ValueError("Card number must be exactly 16 digits")
        return cleaned


class RefundRequest(BaseModel):
    """Request to submit a refund."""
    amount: float = Field(..., gt=0, description="Refund amount in UZS")
    card_id: Optional[int] = Field(None, description="Existing card ID to refund to")
    new_card: Optional[NewCardInput] = Field(None, description="New card details (if not using existing)")

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("Amount must be positive")
        return v
