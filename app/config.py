"""Application configuration."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


class Config:
    """Default configuration values loaded from environment variables."""

    def __init__(self) -> None:
        env_path = Path(__file__).resolve().parent.parent / ".env"
        load_dotenv(env_path, override=False)

        self.FLASK_ENV = os.getenv("FLASK_ENV", "development")
        self.SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key")
        self.SQLALCHEMY_DATABASE_URI = os.getenv(
            "DATABASE_URL", "sqlite:///chronos.db"
        )
        self.SQLALCHEMY_TRACK_MODIFICATIONS = False
        self.DB_ECHO = os.getenv("DB_ECHO", "false").lower() == "true"
        self.SQLALCHEMY_ECHO = self.DB_ECHO
        self.API_TITLE = os.getenv("API_TITLE", "Chronos API")
        self.API_VERSION = os.getenv("API_VERSION", "0.1.0")
        self.ORIGIN = os.getenv("ORIGIN", "http://localhost:8000")


class TestConfig(Config):
    """Configuration for tests with in-memory database."""

    def __init__(self) -> None:
        super().__init__()
        self.SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
        self.TESTING = True
        self.WTF_CSRF_ENABLED = False
