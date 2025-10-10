from flask import Flask
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv
import os

from .config import Config

load_dotenv()

db = SQLAlchemy()
migrate = Migrate()


def create_app(config_class: type[Config] | None = None) -> Flask:
    """Application factory."""
    app = Flask(__name__, template_folder="templates", static_folder="static")
    config_class = config_class or Config
    app.config.from_object(config_class)

    db.init_app(app)
    migrate.init_app(app, db)

    from .routes.dashboard import bp as dashboard_bp
    from .routes.enseignant import bp as enseignant_bp
    from .routes.salle import bp as salle_bp
    from .routes.matiere import bp as matiere_bp
    from .routes.resource import bp as resource_bp

    app.register_blueprint(dashboard_bp)
    app.register_blueprint(enseignant_bp)
    app.register_blueprint(salle_bp)
    app.register_blueprint(matiere_bp)
    app.register_blueprint(resource_bp)

    return app


# Import models for Alembic
from . import models  # noqa: E402,F401
