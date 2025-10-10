"""Route blueprints for Chronos."""
from __future__ import annotations

from .course import bp as course_bp
from .main import bp as main_bp
from .room import bp as room_bp
from .teacher import bp as teacher_bp

__all__ = [
    "main_bp",
    "teacher_bp",
    "room_bp",
    "course_bp",
]
