import os
from datetime import timedelta


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "sqlite:///chronos.db"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ECHO = os.environ.get("DB_ECHO", "false").lower() == "true"
    API_TITLE = os.environ.get("API_TITLE", "Chronos API")
    API_VERSION = os.environ.get("API_VERSION", "0.1.0")
    ORIGIN = os.environ.get("ORIGIN", "http://localhost:8000")
    PERMANENT_SESSION_LIFETIME = timedelta(hours=6)


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_ECHO = False
