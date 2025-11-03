"""API blueprint for Chronos incremental scheduling services."""
from __future__ import annotations

from flask import Blueprint

api_bp = Blueprint("chronos_api", __name__)

from . import planning  # noqa: E402,F401
