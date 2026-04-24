"""Internationalization utilities using Fluent."""
from pathlib import Path
from typing import Any
from fluent.runtime import FluentLocalization, FluentResourceLoader


# Supported languages
SUPPORTED_LANGUAGES = ["uz", "ru"]
DEFAULT_LANGUAGE = "uz"

# Locales directory
LOCALES_DIR = Path(__file__).parent.parent.parent.parent / "locales"


class I18n:
    """i18n manager using Fluent."""

    def __init__(self):
        """Initialize i18n with Fluent loader."""
        self.loader = FluentResourceLoader(str(LOCALES_DIR / "{locale}"))
        self.localizations: dict[str, FluentLocalization] = {}

        # Preload all supported languages
        for lang in SUPPORTED_LANGUAGES:
            self._load_language(lang)

    def _load_language(self, lang: str) -> None:
        """Load language resources."""
        try:
            self.localizations[lang] = FluentLocalization(
                [lang],
                ["main.ftl"],
                self.loader
            )
        except Exception as e:
            print(f"Failed to load language {lang}: {e}")
            if lang != DEFAULT_LANGUAGE:
                # Fallback to default language
                self.localizations[lang] = self.localizations.get(
                    DEFAULT_LANGUAGE,
                    FluentLocalization([DEFAULT_LANGUAGE], ["main.ftl"], self.loader)
                )

    def get(self, lang: str, key: str, **kwargs: Any) -> str:
        """Get translated string."""
        # Fallback to default if language not supported
        if lang not in SUPPORTED_LANGUAGES:
            lang = DEFAULT_LANGUAGE

        localization = self.localizations.get(lang)
        if not localization:
            return key

        # Format message with variables
        formatted = localization.format_value(key, kwargs)
        return formatted if formatted else key

    def get_flag(self, lang: str) -> str:
        """Get flag emoji for language."""
        flags = {
            "uz": "🇺🇿",
            "ru": "🇷🇺"
        }
        return flags.get(lang, "🏳️")


# Global i18n instance
i18n = I18n()


def get_user_language(language_code: str | None) -> str:
    """Get user language from language_code."""
    if not language_code:
        return DEFAULT_LANGUAGE

    # Extract base language (e.g., 'ru' from 'ru-RU')
    base_lang = language_code.split('-')[0].lower()

    return base_lang if base_lang in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE
