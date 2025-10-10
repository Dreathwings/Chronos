from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass
class AppConfig:
    SECRET_KEY: str
    SQLALCHEMY_DATABASE_URI: str
    SQLALCHEMY_TRACK_MODIFICATIONS: bool = False
    API_TITLE: str = "Chronos API"
    API_VERSION: str = "0.1.0"
    ORIGIN: str = "http://localhost:8000"


DEFAULT_DATABASE = "sqlite:///chronos.db"


def load_config() -> dict[str, str | bool]:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    load_dotenv(env_path)

    secret_key = os.getenv("SECRET_KEY", "change_me")
    database_url = os.getenv("DATABASE_URL", DEFAULT_DATABASE)

    return {
        "SECRET_KEY": secret_key,
        "SQLALCHEMY_DATABASE_URI": database_url,
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "API_TITLE": os.getenv("API_TITLE", "Chronos API"),
        "API_VERSION": os.getenv("API_VERSION", "0.1.0"),
        "ORIGIN": os.getenv("ORIGIN", "http://localhost:8000"),
    }
