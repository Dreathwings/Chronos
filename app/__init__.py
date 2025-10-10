"""Application factory for Chronos scheduling app."""
from __future__ import annotations

from flask import Flask
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect

from .config import Config

# Global extensions
db = SQLAlchemy()
migrate = Migrate()
csrf = CSRFProtect()


def create_app(config_class: type[Config] | None = None) -> Flask:
    """Create a configured Flask application."""
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.from_object(config_class or Config())

    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)

    from . import models  # noqa: F401 - ensure models are registered
    from .routes import main_bp, teacher_bp, room_bp, course_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(teacher_bp, url_prefix="/enseignant")
    app.register_blueprint(room_bp, url_prefix="/salle")
    app.register_blueprint(course_bp, url_prefix="/matiere")

    return app
