"""Chronos API blueprint."""

from __future__ import annotations

from flask import Blueprint

bp = Blueprint("chronos_api", __name__)

__all__ = ["bp"]


from . import planning  # noqa: F401
