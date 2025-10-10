from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


load_dotenv()


@dataclass
class Config:
    """Application configuration loaded from environment variables."""

    SECRET_KEY: str = os.getenv("SECRET_KEY", "dev-secret-key")
    SQLALCHEMY_DATABASE_URI: str = os.getenv(
        "DATABASE_URL",
        "sqlite:///chronos.db",
    )
    SQLALCHEMY_TRACK_MODIFICATIONS: bool = False
    API_TITLE: str = os.getenv("API_TITLE", "Chronos API")
    API_VERSION: str = os.getenv("API_VERSION", "0.1.0")
    ORIGIN: str = os.getenv("ORIGIN", "http://localhost:8000")

    @classmethod
    def from_env(cls) -> "Config":
        return cls()
