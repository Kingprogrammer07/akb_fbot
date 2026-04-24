from typing import List, Optional
from pydantic import BaseModel, Field


class CargoItemResponse(BaseModel):
    """Schema for a single cargo item."""
    id: int
    track_code: str
    flight_name: Optional[str] = None
    client_id: Optional[str] = None
    
    # Item details
    item_name_cn: Optional[str] = None
    item_name_ru: Optional[str] = None
    quantity: Optional[str] = None
    weight_kg: Optional[str] = None
    price_per_kg_usd: Optional[str] = None
    price_per_kg_uzs: Optional[str] = None
    total_payment_usd: Optional[str] = None
    total_payment_uzs: Optional[str] = None
    exchange_rate: Optional[str] = None
    box_number: Optional[str] = None
    
    # Status and Dates
    checkin_status: str = Field(..., description="'pre' for China, 'post' for Uzbekistan")
    pre_checkin_date: Optional[str] = None
    post_checkin_date: Optional[str] = None

    # Flight cargo / billing status
    is_sent_web: bool = False
    is_taken_away: bool = False
    taken_away_date: Optional[str] = None
    
    class Config:
        from_attributes = True


class TrackCodeSearchResponse(BaseModel):
    """Schema for track code search results (merged pre/post items)."""
    found: bool
    track_code: str
    items: List[CargoItemResponse] = Field(default_factory=list)
    total_count: int = 0


class FlightStatusResponse(BaseModel):
    """Schema for flight status check results."""
    flight_name: str
    client_code: str
    exists_in_sheets: bool = Field(..., description="Found in Google Sheets")
    exists_in_db: bool = Field(..., description="Found in local FlightCargo database")
    is_sent: bool = Field(..., description="Marked as sent in local database")
    is_taken_away: Optional[bool] = Field(None, description="Cargo taken away status (if transaction exists)")
    taken_away_date: Optional[str] = Field(None, description="Date when cargo was taken away")


from datetime import datetime

class ClientFlightSummary(BaseModel):
    """Schema for client's cargo summary per flight."""
    flight_name: Optional[str] = None
    total_count: int
    total_weight: float
    last_update: Optional[datetime] = None
    
    # Computed/Optional status could be added here if logic permits
    # For now, just returning raw data aggregated
    
    class Config:
        from_attributes = True


class ClientFlightDetailResponse(BaseModel):
    """Schema for detailed flight cargo items."""
    flight_name: Optional[str] = None
    items: List[CargoItemResponse]
    total: int
    page: int
    size: int


class ReportResponse(BaseModel):
    """Schema for web report history response."""
    flight_name: str
    total_weight: float = 0.0
    total_price_usd: float = 0.0
    total_price_uzs: float = 0.0
    is_sent_web_date: Optional[datetime] = None
    photo_file_ids: List[str] = Field(default_factory=list)
    track_codes: List[str] = Field(default_factory=list)

    # Payment info
    payment_status: str = "unpaid"
    paid_amount: float = 0.0
    expected_amount: float = 0.0
    payment_date: Optional[datetime] = None

