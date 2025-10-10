"""Endpoints for launching the optimisation routine and viewing the timetable."""
from __future__ import annotations

from flask import request
from flask_restx import Namespace, Resource, fields

from ..extensions import db
from ..models import Assignment, Course
from ..services.optimizer import persist_assignments, solve_timetable


ns = Namespace("solver", description="Timetable optimisation")

assignment_output = ns.model(
    "AssignmentOutput",
    {
        "id": fields.Integer(readonly=True),
        "course_id": fields.Integer,
        "session_index": fields.Integer,
        "timeslot_id": fields.Integer,
        "room_id": fields.Integer,
        "teacher_id": fields.Integer,
        "status": fields.String,
    },
)

solve_response = ns.model(
    "SolveResponse",
    {
        "created": fields.Integer,
        "assignments": fields.List(fields.Nested(assignment_output)),
    },
)


def serialize_assignment(assignment: Assignment) -> dict[str, int | str]:
    return {
        "id": assignment.id,
        "course_id": assignment.course_id,
        "session_index": assignment.session_index,
        "timeslot_id": assignment.timeslot_id,
        "room_id": assignment.room_id,
        "teacher_id": assignment.teacher_id,
        "status": assignment.status,
    }


@ns.route("/solve")
class SolveResource(Resource):
    @ns.marshal_with(solve_response)
    def post(self) -> dict[str, object]:
        try:
            decisions = solve_timetable(db.session)
        except ValueError as exc:
            ns.abort(400, str(exc))

        assignments = persist_assignments(db.session, decisions)
        return {
            "created": len(assignments),
            "assignments": [serialize_assignment(assignment) for assignment in assignments],
        }


@ns.route("/timetable")
@ns.param("scope", "teacher|group|room")
@ns.param("id", "Identifier associated with the scope")
class TimetableView(Resource):
    @ns.marshal_list_with(assignment_output)
    def get(self) -> list[dict[str, object]]:
        scope = request.args.get("scope")
        identifier = request.args.get("id")

        query = Assignment.query
        if scope and identifier:
            if scope == "teacher":
                query = query.filter_by(teacher_id=int(identifier))
            elif scope == "group":
                query = query.join(Course).filter(Course.group_id == identifier)
            elif scope == "room":
                query = query.filter_by(room_id=int(identifier))
            else:
                ns.abort(400, "scope must be teacher, group or room")

        assignments = query.order_by(Assignment.timeslot_id).all()
        return [serialize_assignment(assignment) for assignment in assignments]
