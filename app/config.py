"""
Application configuration.

Uses environment variables for secrets and database URLs.
Defaults to demo messaging mode so the app works without Twilio credentials.
"""

import os


class Config:
    """Base configuration shared by all environments."""

    # Flask core
    SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-me")

    # Database — default to a local SQLite file for easy first run
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "sqlite:///campus_notify.db"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Messaging — 'demo' or 'twilio'
    MESSAGING_MODE = os.environ.get("MESSAGING_MODE", "demo")

    # Twilio credentials (only needed when MESSAGING_MODE=twilio)
    TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
    TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
    TWILIO_PHONE_NUMBER = os.environ.get("TWILIO_PHONE_NUMBER", "")

    # Timezone for display
    TIMEZONE = "Asia/Kolkata"


class DevelopmentConfig(Config):
    """Local development settings."""

    DEBUG = True


class TestingConfig(Config):
    """Test settings — uses in-memory SQLite, demo messaging, CSRF disabled."""

    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    MESSAGING_MODE = "demo"
    WTF_CSRF_ENABLED = False  # Simplifies form testing
    SERVER_NAME = "localhost"  # Needed for url_for in tests
    RATELIMIT_ENABLED = False  # Disable limits to prevent 429s in tests


class ProductionConfig(Config):
    """Production settings — requires real secret key and database."""

    DEBUG = False
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    RATELIMIT_ENABLED = True


# Map config names to classes for the app factory
config_by_name = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}
