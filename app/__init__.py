from flask import Flask

from .config import load_config
from .database import db
from .views import register_routes


def create_app() -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    config = load_config()
    app.config.update(config)

    db.init_app(app)

    with app.app_context():
        db.create_all()

    register_routes(app)

    return app


app = create_app()
