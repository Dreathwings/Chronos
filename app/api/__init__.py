"""REST API definition using Flask-RESTX."""
from __future__ import annotations

from flask_restx import Api

from .assignments import ns as assignments_ns
from .courses import ns as courses_ns
from .health import ns as health_ns
from .rooms import ns as rooms_ns
from .teachers import ns as teachers_ns
from .timeslots import ns as timeslots_ns
from .solver import ns as solver_ns


def register_namespaces(api: Api) -> None:
    """Register all API namespaces."""
    api.add_namespace(health_ns, path="/health")
    api.add_namespace(teachers_ns, path="/teachers")
    api.add_namespace(rooms_ns, path="/rooms")
    api.add_namespace(courses_ns, path="/courses")
    api.add_namespace(timeslots_ns, path="/timeslots")
    api.add_namespace(assignments_ns, path="/assignments")
    api.add_namespace(solver_ns, path="")
