from __future__ import annotations

from flask import Flask
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy

from .config import config


db = SQLAlchemy()
migrate = Migrate()


def create_app() -> Flask:
    """Application factory for the Chronos planner."""

    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.from_object(config)

    db.init_app(app)
    migrate.init_app(app, db)

    from . import models  # noqa: F401  # ensure models are registered
    from .routes import main_bp

    app.register_blueprint(main_bp)

    @app.shell_context_processor
    def _shell_context():
        from . import models as m

        return {"db": db, **{name: getattr(m, name) for name in m.__all__}}

    return app
