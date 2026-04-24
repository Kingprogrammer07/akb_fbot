"""Admin handlers package."""
from src.bot.handlers.admin.start import admin_start_router
from src.bot.handlers.admin.databases import admin_databases_router
from src.bot.handlers.admin.client_search import client_search_router
from src.bot.handlers.admin.client_verification import client_verification_router
from src.bot.handlers.admin.track_check import track_check_router
from src.bot.handlers.admin.photo_upload import photo_upload_router
from src.bot.handlers.admin.bulk_cargo_sender import router as bulk_cargo_sender_router
from src.bot.handlers.admin.broadcast import broadcast_router
from src.bot.handlers.admin.flight_notify import flight_notify_router
from src.bot.handlers.admin.referral_data import referral_data_router
from src.bot.handlers.admin.settings import settings_router
from src.bot.handlers.admin.get_data import get_data_router
from src.bot.handlers.admin.leftover_cargo import leftover_cargo_router

__all__ = [
    'admin_start_router',
    'admin_databases_router',
    'client_search_router',
    'client_verification_router',
    'track_check_router',
    'photo_upload_router',
    'bulk_cargo_sender_router',
    'broadcast_router',
    'flight_notify_router',
    'referral_data_router',
    'settings_router',
    'get_data_router',
    'leftover_cargo_router',
]
