import os
from pathlib import Path


class Config:
    BASE_DIR = Path(__file__).resolve().parent.parent
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key")
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        f"sqlite:///{(BASE_DIR / 'chronos.db').as_posix()}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    API_TITLE = os.getenv("API_TITLE", "Chronos API")
    API_VERSION = os.getenv("API_VERSION", "0.1.0")
    ORIGIN = os.getenv("ORIGIN", "http://localhost:8000")
    DB_ECHO = os.getenv("DB_ECHO", "false").lower() == "true"
