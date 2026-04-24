"""Passport handlers."""
from src.bot.handlers.passport.add_passport import add_passport_router
from src.bot.handlers.passport.my_passports import my_passports_router

__all__ = ['add_passport_router', 'my_passports_router']
