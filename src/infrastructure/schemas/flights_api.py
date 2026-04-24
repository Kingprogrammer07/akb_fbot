"""Pydantic schemas for flights and cargo photos API."""
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime


# ==================== Flight Schemas ====================

class FlightResponse(BaseModel):
    """Flight/Reys response schema."""
    name: str = Field(..., description="Flight name (e.g., M123-2025)")


class FlightListResponse(BaseModel):
    """List of flights response."""
    flights: List[FlightResponse]
    total: int


# ==================== Client Cargo Data Schemas ====================

class ClientCargoData(BaseModel):
    """Client cargo data from Google Sheets."""
    flight: str
    client_code: str
    row_number: int
    track_codes: List[str]
    weight_kg: Optional[str] = None
    price_per_kg: Optional[str] = None
    total_payment: Optional[str] = None
    payment_status: Optional[str] = None


class FlightClientsResponse(BaseModel):
    """List of clients in a flight."""
    flight: str
    clients: List[ClientCargoData]
    total: int


# ==================== Photo Upload Schemas ====================

class PhotoUploadResponse(BaseModel):
    """Photo upload response schema."""
    success: bool
    message: str
    photo: "CargoPhotoResponse"


class CargoPhotoResponse(BaseModel):
    """Cargo photo response schema (database model)."""
    id: str
    flight_name: str
    client_id: str
    photo_file_ids: List[str]  # Array of file IDs
    weight_kg: Optional[float] = None
    price_per_kg: Optional[float] = None
    comment: Optional[str] = None
    is_sent: bool = False
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class FlightPhotosResponse(BaseModel):
    """Paginated list of photos for a flight."""
    flight_name: str
    photos: List[CargoPhotoResponse]
    total: int
    unique_clients: int
    sent_count: int = Field(..., description="Total sent cargo items across the entire flight")
    unsent_count: int = Field(..., description="Total unsent cargo items across the entire flight")
    page: int = Field(..., description="Current page (1-based)")
    size: int = Field(..., description="Items per page")
    total_pages: int = Field(..., description="Total number of pages")

class ClearPhotosResponse(BaseModel):
    """Response for clearing photos."""
    success: bool
    message: str
    flight_name: Optional[str] = None
    deleted_count: Optional[int] = None


class CargoDeleteResponse(BaseModel):
    """Response for deleting a single cargo."""
    success: bool
    message: str
    deleted_cargo_id: Optional[str] = None


class CargoUpdateResponse(BaseModel):
    """Response for updating a cargo photo."""
    success: bool
    message: str
    photo: CargoPhotoResponse


class FlightStatsResponse(BaseModel):
    """Flight photo statistics."""
    flight_name: str
    total_photos: int
    unique_clients: int
    sent_count: int
    unsent_count: int


# ==================== Image File ID Schemas ====================
# Note: URL schemas removed for security - all images must be accessed via proxy endpoints

class ImageFileIdData(BaseModel):
    """Single image file_id data (secure - no URLs exposed)."""
    index: int = Field(..., description="Index of the photo (0-based)")
    file_id: str = Field(..., description="Telegram file_id - use with proxy endpoint")
    file_size: Optional[int] = Field(None, description="File size in bytes")


# ==================== File ID Resolution Schemas ====================

class CargoPhotoMetadata(BaseModel):
    """
    Single cargo photo metadata with file_id.

    Frontend should use file_id to request image via proxy endpoint
    or resolve via Telegram Bot API.
    """
    index: int = Field(..., description="Photo index (0-based)")
    file_id: str = Field(..., description="Telegram file_id")
    telegram_url: Optional[str] = Field(
        None,
        description="Temporary Telegram URL (expires in ~1 hour). "
                    "May be null if not resolved."
    )
    is_regenerated: bool = Field(
        False,
        description="True if file_id was regenerated due to expiry"
    )
    error: Optional[str] = Field(
        None,
        description="Error message if resolution failed"
    )


class CargoImageMetadataResponse(BaseModel):
    """
    Response for cargo image metadata endpoint.

    Returns file_id(s) and optional URLs instead of binary data.
    This is the new architecture - no binary streaming.
    """
    cargo_id: int = Field(..., description="Cargo ID")
    flight_name: str = Field(..., description="Flight name")
    client_id: str = Field(..., description="Client code")
    photo_count: int = Field(..., description="Number of photos")
    photos: List[CargoPhotoMetadata] = Field(
        default_factory=list,
        description="Photo metadata with file_ids"
    )

    class Config:
        from_attributes = True


class SinglePhotoMetadataResponse(BaseModel):
    """
    Response for single photo file_id resolution.

    Used when frontend needs to refresh a specific photo.
    """
    cargo_id: int = Field(..., description="Cargo ID")
    photo_index: int = Field(..., description="Photo index")
    file_id: str = Field(..., description="Telegram file_id (may be regenerated)")
    telegram_url: Optional[str] = Field(
        None,
        description="Temporary Telegram URL (expires in ~1 hour)"
    )
    is_regenerated: bool = Field(
        False,
        description="True if file_id was regenerated"
    )


class PassportImageMetadata(BaseModel):
    """Single passport image metadata."""
    index: int = Field(..., description="Image index (0-based)")
    file_id: str = Field(..., description="Telegram file_id")
    telegram_url: Optional[str] = Field(None, description="Temporary Telegram URL")
    is_regenerated: bool = Field(False, description="True if regenerated")
    error: Optional[str] = Field(None, description="Error if resolution failed")


class PassportImagesMetadataResponse(BaseModel):
    """Response for passport images metadata."""
    client_id: int = Field(..., description="Client ID")
    image_count: int = Field(..., description="Number of passport images")
    images: List[PassportImageMetadata] = Field(
        default_factory=list,
        description="Passport image metadata"
    )
