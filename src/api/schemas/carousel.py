"""Pydantic schemas for Carousel endpoints."""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator, field_validator


# ---------------------------------------------------------------------------
# Media upload
# ---------------------------------------------------------------------------

CarouselMediaType = Literal["image", "gif", "video"]

_MIME_TO_MEDIA_TYPE: dict[str, CarouselMediaType] = {
    "image/jpeg": "image",
    "image/jpg":  "image",
    "image/png":  "image",
    "image/webp": "image",
    "image/heic": "image",
    "image/gif":  "gif",
    "video/mp4":        "video",
    "video/quicktime":  "video",
    "video/webm":       "video",
    "video/x-msvideo":  "video",
    "video/mpeg":       "video",
}

# Byte limits per media category
_SIZE_LIMITS: dict[CarouselMediaType, int] = {
    "image": 50  * 1024 * 1024,   # 50 MB  — images are typically small
    "gif":   50  * 1024 * 1024,   # 50 MB  — animated GIFs can be large
    "video": 200 * 1024 * 1024,   # 200 MB — proxy for ≤ 90 s at high quality
}

ALLOWED_MIME_TYPES: frozenset[str] = frozenset(_MIME_TO_MEDIA_TYPE.keys())


def mime_to_media_type(mime: str) -> CarouselMediaType | None:
    """Map a MIME type string to a carousel media_type. Returns None if unknown."""
    return _MIME_TO_MEDIA_TYPE.get(mime.lower())


def size_limit_for(media_type: CarouselMediaType) -> int:
    """Return the byte size limit for the given media type."""
    return _SIZE_LIMITS[media_type]


class CarouselMediaUploadResponse(BaseModel):
    """Returned after a successful media upload to S3."""

    s3_key: str = Field(description="S3 object key — store this on the carousel item")
    media_url: str = Field(description="Public HTTPS URL ready to use in media_url field")
    media_type: CarouselMediaType = Field(description="Detected media type: image | gif | video")
    size_bytes: int = Field(description="Uploaded file size in bytes")


# ---------------------------------------------------------------------------
# Carousel item CRUD
# ---------------------------------------------------------------------------

class CarouselItemCreate(BaseModel):
    """Schema for creating a carousel item.

    **Ad type**: provide exactly one of ``media_url`` or ``media_s3_key`` for the
    primary (single) media.

    **Feature type**: either provide the primary media fields (same as ad) OR
    provide ``media_items`` list (up to 20 images, 20 GIFs, 5 videos).
    Both approaches can be combined: primary fields set the item's own columns
    while ``media_items`` populates the related media table.
    """

    type: str = Field(..., description="Item type: 'ad' or 'feature'")
    title: Optional[str] = Field(None, description="Display title")
    sub_title: Optional[str] = Field(None, description="Display subtitle")
    media_type: CarouselMediaType = Field(..., description="Primary media type: image | gif | video")
    media_url: Optional[str] = Field(None, description="External media URL (mutually exclusive with media_s3_key)")
    media_s3_key: Optional[str] = Field(None, description="S3 key from upload endpoint (mutually exclusive with media_url)")
    # Feature-type only: list of additional media items.
    media_items: Optional[list[CarouselMediaItemInput]] = Field(
        None,
        description="Multiple media entries (feature type only). Max: 20 images, 20 GIFs, 5 videos.",
    )
    action_url: Optional[str] = Field(None, description="URL opened on click")
    text_color: str = Field("#ffffff", description="Text color hex code")
    gradient: Optional[str] = Field(None, description="CSS gradient string")
    order: int = Field(0, description="Display order (ascending)")
    is_active: bool = Field(True, description="Whether item is visible")

    @model_validator(mode="after")
    def validate_media_sources(self) -> "CarouselItemCreate":
        has_url = bool(self.media_url)
        has_key = bool(self.media_s3_key)
        has_items = bool(self.media_items)

        # For feature type, media_items alone is sufficient.
        if self.type == "feature" and has_items and not has_url and not has_key:
            return self

        # Otherwise exactly one of media_url / media_s3_key must be provided.
        if not has_url and not has_key:
            raise ValueError("Provide either media_url or media_s3_key.")
        if has_url and has_key:
            raise ValueError("Provide only one of media_url or media_s3_key, not both.")

        # media_items only allowed for feature type.
        if has_items and self.type != "feature":
            raise ValueError("media_items is only allowed for 'feature' type items.")

        return self


class CarouselItemUpdate(BaseModel):
    """Schema for updating a carousel item. All fields optional.

    For feature items, supply ``media_items`` to **replace** the full media list.
    Omitting ``media_items`` leaves the existing list untouched.
    """

    type: Optional[str] = None
    title: Optional[str] = None
    sub_title: Optional[str] = None
    media_type: Optional[CarouselMediaType] = None
    media_url: Optional[str] = None
    media_s3_key: Optional[str] = None
    # When provided, replaces the entire media list for the feature item.
    media_items: Optional[list[CarouselMediaItemInput]] = None
    action_url: Optional[str] = None
    text_color: Optional[str] = None
    gradient: Optional[str] = None
    order: Optional[int] = None
    is_active: Optional[bool] = None


# ---------------------------------------------------------------------------
# Multi-media (feature items)
# ---------------------------------------------------------------------------

class CarouselMediaItemInput(BaseModel):
    """A single media entry when creating/updating a feature carousel item.

    Provide exactly one of ``media_s3_key`` (uploaded via /upload endpoint)
    or ``media_url`` (external link).
    """

    media_type: CarouselMediaType
    media_s3_key: Optional[str] = Field(None, description="S3 key from /upload endpoint")
    media_url: Optional[str] = Field(None, description="External media URL")
    order: int = Field(0, ge=0, description="Display order within the item")

    @model_validator(mode="after")
    def require_exactly_one_source(self) -> "CarouselMediaItemInput":
        has_key = bool(self.media_s3_key)
        has_url = bool(self.media_url)
        if not has_key and not has_url:
            raise ValueError("Provide either media_s3_key or media_url.")
        if has_key and has_url:
            raise ValueError("Provide only one of media_s3_key or media_url, not both.")
        return self


class CarouselMediaItemResponse(BaseModel):
    """A single resolved media entry returned in carousel item responses."""

    id: int
    media_type: CarouselMediaType
    # Resolved URL: presigned if S3-backed, raw if external.
    media_url: str
    media_s3_key: Optional[str] = None
    order: int

    class Config:
        from_attributes = True


# Per-item limits for feature type.
FEATURE_MEDIA_LIMITS: dict[str, int] = {"image": 20, "gif": 20, "video": 5}


# ---------------------------------------------------------------------------
# Carousel item CRUD
# ---------------------------------------------------------------------------

class CarouselItemResponse(BaseModel):
    """Schema for carousel item API response."""

    id: int
    type: str
    title: Optional[str] = None
    sub_title: Optional[str] = None
    media_type: str
    media_url: str
    media_s3_key: Optional[str] = None
    action_url: Optional[str] = None
    text_color: str
    gradient: Optional[str] = None
    order: int
    is_active: bool
    created_at: datetime
    # Populated for 'feature' items; empty list for 'ad' items.
    media_items: list[CarouselMediaItemResponse] = Field(default_factory=list)

    class Config:
        from_attributes = True


class CarouselItemStatsResponse(BaseModel):
    """Schema for carousel item with aggregated stats."""

    id: int
    type: str
    title: Optional[str] = None
    sub_title: Optional[str] = None
    media_type: str
    media_url: str
    media_s3_key: Optional[str] = None
    action_url: Optional[str] = None
    text_color: str
    gradient: Optional[str] = None
    order: int
    is_active: bool
    created_at: datetime
    total_views: int = 0
    total_clicks: int = 0
    media_items: list[CarouselMediaItemResponse] = Field(default_factory=list)

    class Config:
        from_attributes = True
