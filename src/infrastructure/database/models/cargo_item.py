"""Cargo item model for tracking shipments."""
from sqlalchemy import Column, String, Boolean
from src.infrastructure.database.models.base import Base


class CargoItem(Base):
    """
    Cargo item model for tracking pre-flight (China) and post-flight (Uzbekistan) shipments.

    Attributes:
        flight_name: Name of the flight/shipment batch
        client_id: Client's unique identifier (e.g., SS123)
        track_code: Tracking code for the item
        total_weight: Total weight for the client's shipment
        item_name_cn: Item name in Chinese
        item_name_ru: Item name in Russian
        quantity: Number of items
        weight_kg: Weight in kilograms
        price_per_kg: Price per kilogram
        total_payment: Total payment amount
        box_number: Box number
        checkin_status: Status of the item ('pre' for China, 'post' for Uzbekistan)
        pre_checkin_date: Date when checked in China
        post_checkin_date: Date when checked in Uzbekistan
    """
    __tablename__ = "cargo_items"

    # id, created_at, updated_at inherited from Base
    flight_name = Column(String(100), nullable=True)
    client_id = Column(String(100), nullable=True, index=True)
    track_code = Column(String(100), nullable=True, index=True)

    total_weight = Column(String(100), nullable=True)
    item_name_cn = Column(String(100), nullable=True)
    item_name_ru = Column(String(100), nullable=True)
    quantity = Column(String(100), nullable=True)
    weight_kg = Column(String(100), nullable=True)
    price_per_kg = Column(String(100), nullable=True)
    total_payment = Column(String(100), nullable=True)
    box_number = Column(String(100), nullable=True)

    checkin_status = Column(
        String(10),
        nullable=False,
        default="pre",
        comment="pre=CHINA, post=UZBEKISTAN"
    )

    pre_checkin_date = Column(String(100), nullable=True)
    post_checkin_date = Column(String(100), nullable=True)

    is_used = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment="Flag to track if cargo item has been used"
    )

    # S3 object key for the product image uploaded via the partner API.
    # NULL for items that have no photo or were imported via Excel.
    photo_s3_key = Column(
        String(1024),
        nullable=True,
        comment="S3 key for product image (china_import_image/); NULL if no photo",
    )

    def __repr__(self):
        return f"<CargoItem(id={self.id}, client_id={self.client_id}, track_code={self.track_code}, status={self.checkin_status})>"
