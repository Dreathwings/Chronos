from __future__ import annotations

from flask import Flask

from .config import Config
from .extensions import db, migrate
from .routes import bp


def create_app(config_class: type[Config] = Config) -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.from_object(config_class)

    db.init_app(app)
    migrate.init_app(app, db)

    app.register_blueprint(bp)

    @app.shell_context_processor
    def _shell_context():
        from . import models

        return {"db": db, "models": models}

    return app


app = create_app()
