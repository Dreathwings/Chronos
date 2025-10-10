"""Teacher CRUD endpoints."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from flask import request
from flask_restx import Namespace, Resource, fields

from ..extensions import db
from ..models import Teacher, TeacherAvailability, TeacherUnavailability


ns = Namespace("teachers", description="CRUD operations for teachers")

availability_model = ns.model(
    "TeacherAvailability",
    {
        "id": fields.Integer(readonly=True),
        "weekday": fields.Integer(required=True, min=0, max=6),
        "start_time": fields.String(required=True, description="HH:MM"),
        "end_time": fields.String(required=True, description="HH:MM"),
    },
)

unavailability_model = ns.model(
    "TeacherUnavailability",
    {
        "id": fields.Integer(readonly=True),
        "date": fields.String(required=True, description="YYYY-MM-DD"),
        "start_time": fields.String(required=True, description="HH:MM"),
        "end_time": fields.String(required=True, description="HH:MM"),
    },
)

teacher_model = ns.model(
    "Teacher",
    {
        "id": fields.Integer(readonly=True),
        "name": fields.String(required=True),
        "max_weekly_load_hrs": fields.Integer(default=20),
        "availabilities": fields.List(fields.Nested(availability_model)),
        "unavailabilities": fields.List(fields.Nested(unavailability_model)),
    },
)


def _parse_time(value: str) -> Any:
    return datetime.strptime(value, "%H:%M").time()


def _parse_date(value: str) -> Any:
    return datetime.strptime(value, "%Y-%m-%d").date()


def serialize_teacher(teacher: Teacher) -> dict[str, Any]:
    return {
        "id": teacher.id,
        "name": teacher.name,
        "max_weekly_load_hrs": teacher.max_weekly_load_hrs,
        "availabilities": [
            {
                "id": availability.id,
                "weekday": availability.weekday,
                "start_time": availability.start_time.strftime("%H:%M"),
                "end_time": availability.end_time.strftime("%H:%M"),
            }
            for availability in teacher.availabilities
        ],
        "unavailabilities": [
            {
                "id": unavailability.id,
                "date": unavailability.date.isoformat(),
                "start_time": unavailability.start_time.strftime("%H:%M"),
                "end_time": unavailability.end_time.strftime("%H:%M"),
            }
            for unavailability in teacher.unavailabilities
        ],
    }


@ns.route("")
class TeacherList(Resource):
    """List and create teachers."""

    @ns.marshal_list_with(teacher_model)
    def get(self) -> list[dict[str, Any]]:
        teachers = Teacher.query.order_by(Teacher.name).all()
        return [serialize_teacher(teacher) for teacher in teachers]

    @ns.expect(teacher_model, validate=True)
    @ns.marshal_with(teacher_model, code=201)
    def post(self) -> dict[str, Any]:
        payload = request.json or {}
        teacher = Teacher(
            name=payload["name"],
            max_weekly_load_hrs=payload.get("max_weekly_load_hrs", 20),
        )
        db.session.add(teacher)
        db.session.flush()
        _sync_availability(teacher, payload.get("availabilities", []))
        _sync_unavailability(teacher, payload.get("unavailabilities", []))
        db.session.commit()
        return serialize_teacher(teacher), 201


@ns.route("/<int:teacher_id>")
@ns.param("teacher_id", "Teacher unique identifier")
class TeacherResource(Resource):
    """Retrieve, update or delete a teacher."""

    @ns.marshal_with(teacher_model)
    def get(self, teacher_id: int) -> dict[str, Any]:
        teacher = Teacher.query.get_or_404(teacher_id)
        return serialize_teacher(teacher)

    @ns.expect(teacher_model, validate=True)
    @ns.marshal_with(teacher_model)
    def put(self, teacher_id: int) -> dict[str, Any]:
        teacher = Teacher.query.get_or_404(teacher_id)
        payload = request.json or {}
        teacher.name = payload["name"]
        teacher.max_weekly_load_hrs = payload.get("max_weekly_load_hrs", 20)
        _sync_availability(teacher, payload.get("availabilities", []))
        _sync_unavailability(teacher, payload.get("unavailabilities", []))
        db.session.commit()
        return serialize_teacher(teacher)

    def delete(self, teacher_id: int) -> tuple[dict[str, str], int]:
        teacher = Teacher.query.get_or_404(teacher_id)
        db.session.delete(teacher)
        db.session.commit()
        return {"status": "deleted"}, 204


def _sync_availability(teacher: Teacher, payload: list[dict[str, Any]]) -> None:
    teacher.availabilities.clear()
    for item in payload:
        availability = TeacherAvailability(
            teacher=teacher,
            weekday=item["weekday"],
            start_time=_parse_time(item["start_time"]),
            end_time=_parse_time(item["end_time"]),
        )
        teacher.availabilities.append(availability)


def _sync_unavailability(teacher: Teacher, payload: list[dict[str, Any]]) -> None:
    teacher.unavailabilities.clear()
    for item in payload:
        unavailability = TeacherUnavailability(
            teacher=teacher,
            date=_parse_date(item["date"]),
            start_time=_parse_time(item["start_time"]),
            end_time=_parse_time(item["end_time"]),
        )
        teacher.unavailabilities.append(unavailability)
