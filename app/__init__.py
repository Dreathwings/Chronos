from __future__ import annotations

from flask import Flask

from .config import Config
from .extensions import db, migrate
from .routes import bp as main_bp


def create_app(config: Config | None = None) -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")

    cfg = config or Config.from_env()
    app.config.from_object(cfg)

    db.init_app(app)
    migrate.init_app(app, db)

    app.register_blueprint(main_bp)

    @app.shell_context_processor
    def make_shell_context() -> dict[str, object]:
        from . import models

        return {"db": db, **{name: getattr(models, name) for name in dir(models) if name[0].isupper()}}

    return app
