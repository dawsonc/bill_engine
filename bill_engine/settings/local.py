"""
Local development settings for bill_engine project.
"""

import os

from .base import *  # noqa: F403, F401

# Development-specific settings
DEBUG = True

ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

# Use SQLite for local development if PostgreSQL is not available
# To use PostgreSQL, set up the database and update .env file
if not os.getenv("DATABASE_PASSWORD"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",  # noqa: F405
        }
    }

# Email backend for development (prints to console)
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
