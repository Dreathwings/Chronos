"""Flask extensions used by the application."""
from __future__ import annotations

from flask_migrate import Migrate
from flask_restx import Api
from flask_sqlalchemy import SQLAlchemy


db = SQLAlchemy()
migrate = Migrate()
api = Api(version="0.1.0", title="Chronos API", doc="/api/docs", prefix="/api")
