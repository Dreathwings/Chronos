"""Application factory for Chronos timetable planner."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from flask import Flask
from flask_cors import CORS

from .config import get_config
from .extensions import api as restx_api, db, migrate
from .api import register_namespaces
from .web import web_bp


log = logging.getLogger(__name__)


def create_app(config_name: str | None = None) -> Flask:
    """Application factory used by flask command line."""
    # Load environment variables from .env if present
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)

    app = Flask(__name__)

    config_obj = get_config(config_name)
    app.config.from_object(config_obj)

    configure_extensions(app)
    register_namespaces(restx_api)
    app.register_blueprint(web_bp)

    CORS(app, resources={r"/api/*": {"origins": app.config.get("ORIGIN", "*")}})

    @app.shell_context_processor
    def _shell_context() -> dict[str, Any]:
        return {"db": db}

    return app


def configure_extensions(app: Flask) -> None:
    """Initialise Flask extensions."""
    db.init_app(app)
    migrate.init_app(app, db)
    restx_api.init_app(app)
    restx_api.title = app.config.get("API_TITLE", "Chronos API")
    restx_api.version = app.config.get("API_VERSION", "0.1.0")
