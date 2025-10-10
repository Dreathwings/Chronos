"""Healthcheck endpoint."""
from __future__ import annotations

from flask_restx import Namespace, Resource
from sqlalchemy import text

from ..extensions import db


ns = Namespace("health", description="Service health status")


@ns.route("/health")
class HealthResource(Resource):
    """Simple health check returning database connectivity."""

    def get(self) -> dict[str, str]:
        try:
            db.session.execute(text("SELECT 1"))
            db_ok = "ok"
        except Exception:  # pragma: no cover - log failure
            db.session.rollback()
            db_ok = "error"
        return {"status": "ok", "database": db_ok}
