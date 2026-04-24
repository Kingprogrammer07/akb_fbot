"""Pydantic schemas for User Delivery Request endpoints."""
import json
from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class FlightItem(BaseModel):
    """Single flight in the paid flights list."""
    flight_name: str


class PaidFlightsResponse(BaseModel):
    """Response for GET /flights — list of paid flights."""
    flights: list[FlightItem]


class CalculateUzpostRequest(BaseModel):
    """Request body for POST /calculate-uzpost."""
    flight_names: list[str] = Field(..., min_length=1)


class CardInfo(BaseModel):
    """Payment card details."""
    card_number: str
    card_owner: str


class CalculateUzpostResponse(BaseModel):
    """Response for POST /calculate-uzpost."""
    total_weight: float
    price_per_kg: int
    total_amount: int
    wallet_balance: float
    card: Optional[CardInfo] = None
    warning: Optional[str] = None


class StandardDeliveryRequest(BaseModel):
    """Request body for POST /request/standard (Yandex, AKB, BTS)."""
    delivery_type: Literal["yandex", "akb", "bts"]
    flight_names: list[str] = Field(..., min_length=1)


class DeliverySuccessResponse(BaseModel):
    """Success response after delivery request creation."""
    message: str
    delivery_request_id: int


class DeliveryRequestHistoryItem(BaseModel):
    """Single delivery request in history."""
    id: int
    delivery_type: str
    flight_names: List[str]
    region: str
    address: str
    status: str
    admin_comment: Optional[str] = None
    created_at: datetime
    processed_at: Optional[datetime] = None

    @field_validator('flight_names', mode='before')
    @classmethod
    def parse_flight_names(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return []
        return v

    class Config:
        from_attributes = True


class DeliveryHistoryResponse(BaseModel):
    """Response for GET /history — paginated list of delivery requests."""
    requests: List[DeliveryRequestHistoryItem]
    total_count: int
    page: int
    size: int
    has_next: bool
