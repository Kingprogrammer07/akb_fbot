from src.infrastructure.database.models.client import Client
from src.infrastructure.database.models.client_extra_passport import ClientExtraPassport
from src.infrastructure.database.models.payment_card import PaymentCard
from src.infrastructure.database.models.client_transaction import ClientTransaction
from src.infrastructure.database.models.client_payment_event import ClientPaymentEvent
from src.infrastructure.database.models.cargo_item import CargoItem
from src.infrastructure.database.models.static_data import StaticData
from src.infrastructure.database.models.broadcast import (
    BroadcastMessage,
    BroadcastStatus,
    BroadcastMediaType,
)
from src.infrastructure.database.models.analytics_event import AnalyticsEvent
from src.infrastructure.database.models.api_request_log import APIRequestLog
from src.infrastructure.database.models.stats_daily_clients import StatsDailyClients
from src.infrastructure.database.models.stats_daily_cargo import StatsDailyCargo
from src.infrastructure.database.models.stats_daily_payments import StatsDailyPayments
from src.infrastructure.database.models.user_payment_card import UserPaymentCard
from src.infrastructure.database.models.session_log import SessionLog
from src.infrastructure.database.models.carousel_item import CarouselItem
from src.infrastructure.database.models.carousel_item_media import CarouselItemMedia
from src.infrastructure.database.models.carousel_stat import CarouselStat
from src.infrastructure.database.models.notification import Notification

# ── Admin RBAC models (must be imported so Alembic autogenerate sees them) ──
from src.infrastructure.database.models.role import Role, Permission, role_permissions
from src.infrastructure.database.models.admin_account import AdminAccount
from src.infrastructure.database.models.admin_passkey import AdminPasskey
from src.infrastructure.database.models.admin_audit_log import AdminAuditLog
from src.infrastructure.database.models.cargo_delivery_proof import CargoDeliveryProof
from src.infrastructure.database.models.partner_shipment_temp import PartnerShipmentTemp
from src.infrastructure.database.models.expected_cargo import ExpectedFlightCargo
from src.infrastructure.database.models.flight_schedule import FlightSchedule

__all__ = [
    # Existing models
    "Client",
    "ClientExtraPassport",
    "PaymentCard",
    "ClientTransaction",
    "ClientPaymentEvent",
    "CargoItem",
    "StaticData",
    "BroadcastMessage",
    "BroadcastStatus",
    "BroadcastMediaType",
    "AnalyticsEvent",
    "APIRequestLog",
    "StatsDailyClients",
    "StatsDailyCargo",
    "StatsDailyPayments",
    "UserPaymentCard",
    "SessionLog",
    "CarouselItem",
    "CarouselItemMedia",
    "CarouselStat",
    "Notification",
    # Admin RBAC models
    "Role",
    "Permission",
    "role_permissions",
    "AdminAccount",
    "AdminPasskey",
    "AdminAuditLog",
    "CargoDeliveryProof",
    "PartnerShipmentTemp",
    "ExpectedFlightCargo",
    "FlightSchedule",
]
