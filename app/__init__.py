from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask.cli import with_appcontext

from config import Config


db = SQLAlchemy()
migrate = Migrate()


def create_app(config_class: type[Config] = Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    migrate.init_app(app, db)

    from . import models  # noqa: F401  # Ensure models registered for migrations

    with app.app_context():
        db.create_all()

    from .routes import bp as main_bp

    app.register_blueprint(main_bp)

    @app.cli.command("seed")
    @with_appcontext
    def seed() -> None:
        """Seed initial data for development."""
        from .seed import seed_data

        seed_data()
        print("Database seeded with sample data.")

    return app
