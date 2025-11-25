import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _normalise_prefix(raw_prefix: str) -> str:
    raw_prefix = raw_prefix.strip()
    if not raw_prefix or raw_prefix == "/":
        return ""
    if not raw_prefix.startswith("/"):
        raw_prefix = f"/{raw_prefix}"
    return raw_prefix.rstrip("/")


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key")

    DEBUG = os.environ.get("CHRONOS_DEBUG", "1") not in {"0", "false", "False"}

    URL_PREFIX = _normalise_prefix(os.environ.get("CHRONOS_URL_PREFIX", "/chronos"))

    _default_sqlite = BASE_DIR / "chronos.sqlite3"
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", f"sqlite:///{_default_sqlite}"
    )


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
