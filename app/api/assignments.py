"""Assignment endpoints for manual adjustments and listing."""
from __future__ import annotations

from typing import Any

from flask import request
from flask_restx import Namespace, Resource, fields

from ..extensions import db
from ..models import Assignment, Room, Timeslot


ns = Namespace("assignments", description="Manage generated assignments")

assignment_model = ns.model(
    "Assignment",
    {
        "id": fields.Integer(readonly=True),
        "course_id": fields.Integer(required=True),
        "session_index": fields.Integer(required=True),
        "timeslot_id": fields.Integer(required=True),
        "room_id": fields.Integer(required=True),
        "teacher_id": fields.Integer(required=True),
        "status": fields.String(required=True, default="scheduled"),
    },
)


assignment_patch = ns.model(
    "AssignmentPatch",
    {
        "timeslot_id": fields.Integer,
        "room_id": fields.Integer,
        "status": fields.String,
    },
)


def serialize_assignment(assignment: Assignment) -> dict[str, Any]:
    return {
        "id": assignment.id,
        "course_id": assignment.course_id,
        "session_index": assignment.session_index,
        "timeslot_id": assignment.timeslot_id,
        "room_id": assignment.room_id,
        "teacher_id": assignment.teacher_id,
        "status": assignment.status,
    }


@ns.route("")
class AssignmentList(Resource):
    @ns.marshal_list_with(assignment_model)
    def get(self) -> list[dict[str, Any]]:
        assignments = Assignment.query.order_by(Assignment.course_id, Assignment.session_index).all()
        return [serialize_assignment(assignment) for assignment in assignments]


@ns.route("/<int:assignment_id>")
class AssignmentResource(Resource):
    @ns.marshal_with(assignment_model)
    def get(self, assignment_id: int) -> dict[str, Any]:
        assignment = Assignment.query.get_or_404(assignment_id)
        return serialize_assignment(assignment)

    @ns.expect(assignment_patch, validate=True)
    @ns.marshal_with(assignment_model)
    def patch(self, assignment_id: int) -> dict[str, Any]:
        assignment = Assignment.query.get_or_404(assignment_id)
        payload = request.json or {}

        if "timeslot_id" in payload:
            Timeslot.query.get_or_404(payload["timeslot_id"])
            assignment.timeslot_id = payload["timeslot_id"]
        if "room_id" in payload:
            Room.query.get_or_404(payload["room_id"])
            assignment.room_id = payload["room_id"]
        if "status" in payload:
            assignment.status = payload["status"]

        db.session.commit()
        return serialize_assignment(assignment)

    def delete(self, assignment_id: int) -> tuple[dict[str, str], int]:
        assignment = Assignment.query.get_or_404(assignment_id)
        db.session.delete(assignment)
        db.session.commit()
        return {"status": "deleted"}, 204
