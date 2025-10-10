"""Configuration objects for the Chronos application."""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def get_config(name: str | None = None) -> type[BaseConfig]:
    mapping = {
        "development": DevelopmentConfig,
        "production": ProductionConfig,
        "testing": TestingConfig,
    }
    if name is None:
        name = os.getenv("FLASK_ENV", "development")
    return mapping.get(name, DevelopmentConfig)


class BaseConfig:
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL", f"sqlite:///{BASE_DIR / 'chronos.db'}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = os.getenv("SECRET_KEY", "change_me")
    API_TITLE = os.getenv("API_TITLE", "Chronos API")
    API_VERSION = os.getenv("API_VERSION", "0.1.0")
    RESTX_MASK_SWAGGER = False
    ORIGIN = os.getenv("ORIGIN", "*")


class DevelopmentConfig(BaseConfig):
    DEBUG = True
    DB_ECHO = os.getenv("DB_ECHO", "false").lower() == "true"
    SQLALCHEMY_ECHO = DB_ECHO


class ProductionConfig(BaseConfig):
    DEBUG = False


class TestingConfig(BaseConfig):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
