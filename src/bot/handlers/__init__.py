from src.bot.handlers.admin.access_denied import admin_access_denied_router
from src.bot.handlers.admin.messages import admin_messages_router
from src.bot.handlers.admin.approval import approval_router
from src.bot.handlers.admin.payment_approval import payment_approval_router
from src.bot.handlers.admin.wallet_admin import wallet_admin_router
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
from src.bot.handlers.admin.etijorat_admin import etijorat_admin_router
from src.bot.handlers.admin.partners import partners_admin_router
from src.bot.handlers.commands import commands_router
from src.bot.handlers.language import language_router
from src.bot.handlers.user.messages import user_messages_router
from src.bot.handlers.user.china_address import china_address_router
from src.bot.handlers.user.contact import contact_router
from src.bot.handlers.user.profile import profile_router
from src.bot.handlers.user.services import services_router
from src.bot.handlers.user.info import info_router
from src.bot.handlers.user.track_code import track_code_router
from src.bot.handlers.user.invite_friends import invite_friends_router
from src.bot.handlers.user.make_payment import make_payment_router
from src.bot.handlers.user.delivery_request import delivery_request_router
from src.bot.handlers.user.wallet import wallet_router
# from src.bot.handlers.user.etijorat import etijorat_user_router  # E-tijorat vaqtinchalik o'chirilgan
from src.bot.handlers.passport import add_passport_router, my_passports_router

ROUTERS = [
    # Admin routers (higher priority)
    admin_start_router,  # Admin /start handler - highest priority
    admin_databases_router,  # Admin databases import
    client_search_router,  # Admin client search
    client_verification_router,  # Admin client verification
    track_check_router,  # Admin track code check
    photo_upload_router,  # Admin photo upload (WebApp)
    bulk_cargo_sender_router,  # Admin bulk cargo photo sender
    broadcast_router,  # Admin broadcast announcements
    flight_notify_router,  # Admin per-flight track-code notifications
    referral_data_router,  # Admin referral data export
    get_data_router,  # Admin get client data
    leftover_cargo_router,  # Admin leftover cargo export
    settings_router,  # Admin settings
    partners_admin_router,  # Admin partner CRUD (/partners)
    admin_messages_router,
    approval_router,
    payment_approval_router,
    wallet_admin_router,  # Wallet refund/debt admin handlers
    etijorat_admin_router,  # E-tijorat screenshot approval
    admin_access_denied_router,

    # Command routers
    commands_router,
    language_router,

    # E-tijorat user flow (FSM state + callback) — vaqtinchalik o'chirilgan
    # etijorat_user_router,

    # Passport routers (with FSM states)
    add_passport_router,
    my_passports_router,

    # User routers - Profile, Services, Info, Track Code, Contact, China Address, Invite Friends, Make Payment
    profile_router,
    services_router,
    info_router,
    track_code_router,
    invite_friends_router,
    make_payment_router,
    delivery_request_router,
    wallet_router,  # User wallet handler
    contact_router,
    china_address_router,

    # Other routers

    # User messages (lowest priority - catch all text)
    user_messages_router,
]

__all__ = ['ROUTERS']
