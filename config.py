import os

def _normalise_prefix(raw_prefix: str) -> str:
    raw_prefix = raw_prefix.strip()
    if not raw_prefix or raw_prefix == "/":
        return ""
    if not raw_prefix.startswith("/"):
        raw_prefix = f"/{raw_prefix}"
    return raw_prefix.rstrip("/")


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key")

    URL_PREFIX = _normalise_prefix(os.environ.get("FLASK_URL_PREFIX", "/chronos"))

    _db_user = os.environ.get("DATABASE_USER", "warren")
    _db_password = os.environ.get("DATABASE_PASSWORD", "EPKdVcgcaBYh2l*b")
    _db_host = os.environ.get("DATABASE_HOST", "localhost")
    _db_port = os.environ.get("DATABASE_PORT", "3306")
    _db_name = os.environ.get("DATABASE_NAME", "chronos")

    _default_uri = (
        f"mysql+pymysql://{_db_user}:{_db_password}@{_db_host}:{_db_port}/{_db_name}"
    )

    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", _default_uri)
    SCHEDULE_SEARCH_TIME_LIMIT = float(os.environ.get("SCHEDULE_SEARCH_TIME_LIMIT", "5.0"))
    SCHEDULE_SEARCH_ITERATION_LIMIT = int(
        os.environ.get("SCHEDULE_SEARCH_ITERATION_LIMIT", "20000")
    )
    SCHEDULE_ALLOW_PARTIAL_COMMIT = (
        os.environ.get("SCHEDULE_ALLOW_PARTIAL_COMMIT", "0").lower() in {"1", "true", "yes"}
    )

class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
