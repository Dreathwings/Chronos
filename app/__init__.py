import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask

from .database import init_engine, init_session_factory
from .views import register_blueprints


def create_app(test_config: dict | None = None) -> Flask:
    """Application factory for the Chronos scheduler."""
    project_root = Path(__file__).resolve().parent.parent
    load_dotenv(project_root / ".env")

    app = Flask(__name__, template_folder=str(project_root / "templates"), static_folder=str(project_root / "static"))

    app.config.from_mapping(
        SECRET_KEY=os.getenv("SECRET_KEY", "dev"),
        DATABASE_URL=os.getenv("DATABASE_URL", "sqlite+pysqlite:///" + str(project_root / "chronos.db")),
        API_TITLE=os.getenv("API_TITLE", "Chronos API"),
        API_VERSION=os.getenv("API_VERSION", "0.1.0"),
    )

    if test_config:
        app.config.update(test_config)

    engine = init_engine(app.config["DATABASE_URL"], echo=os.getenv("DB_ECHO", "false").lower() == "true")
    session_factory = init_session_factory(engine)

    app.session_factory = session_factory  # type: ignore[attr-defined]
    should_create_schema = not app.config.get("DISABLE_AUTO_CREATE", False)
    register_blueprints(app, create_schema=should_create_schema)

    @app.teardown_appcontext
    def shutdown_session(exception: BaseException | None = None) -> None:
        session_factory.remove()

    return app


__all__ = ["create_app"]
