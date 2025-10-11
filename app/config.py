from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"
if ENV_PATH.exists():
    load_dotenv(ENV_PATH)


@dataclass
class Config:
    """Application configuration loaded from environment variables."""

    SECRET_KEY: str = os.getenv("SECRET_KEY", "change_me")
    SQLALCHEMY_DATABASE_URI: str = os.getenv("DATABASE_URL", "sqlite:///chronos.db")
    SQLALCHEMY_TRACK_MODIFICATIONS: bool = False
    SQLALCHEMY_ECHO: bool = os.getenv("DB_ECHO", "false").lower() == "true"
    API_TITLE: str = os.getenv("API_TITLE", "Chronos API")
    API_VERSION: str = os.getenv("API_VERSION", "0.1.0")
    ORIGIN: str = os.getenv("ORIGIN", "http://localhost:8000")


config = Config()
