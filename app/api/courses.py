"""Course CRUD endpoints."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from flask import request
from flask_restx import Namespace, Resource, fields

from ..extensions import db
from ..models import ClassGroup, Course, CourseRequirement, Teacher


ns = Namespace("courses", description="CRUD operations for courses")

requirement_model = ns.model(
    "CourseRequirement",
    {
        "id": fields.Integer(readonly=True),
        "key": fields.String(required=True),
        "value": fields.String(required=True),
    },
)

course_model = ns.model(
    "Course",
    {
        "id": fields.Integer(readonly=True),
        "name": fields.String(required=True),
        "group_id": fields.String(required=True),
        "class_group_name": fields.String(readonly=True),
        "size": fields.Integer(required=True),
        "teacher_id": fields.Integer(required=True),
        "sessions_count": fields.Integer(required=True, min=1),
        "session_minutes": fields.Integer(required=True, min=30),
        "window_start": fields.String(required=True, description="YYYY-MM-DD"),
        "window_end": fields.String(required=True, description="YYYY-MM-DD"),
        "requirements": fields.List(fields.Nested(requirement_model)),
    },
)


def serialize_course(course: Course) -> dict[str, Any]:
    return {
        "id": course.id,
        "name": course.name,
        "group_id": course.group_id,
        "class_group_name": course.class_group.name if course.class_group else None,
        "size": course.size,
        "teacher_id": course.teacher_id,
        "sessions_count": course.sessions_count,
        "session_minutes": course.session_minutes,
        "window_start": course.window_start.isoformat(),
        "window_end": course.window_end.isoformat(),
        "requirements": [
            {"id": requirement.id, "key": requirement.key, "value": requirement.value}
            for requirement in course.requirements
        ],
    }


def _parse_date(value: str) -> datetime.date:
    return datetime.strptime(value, "%Y-%m-%d").date()


@ns.route("")
class CourseList(Resource):
    @ns.marshal_list_with(course_model)
    def get(self) -> list[dict[str, Any]]:
        courses = Course.query.order_by(Course.name).all()
        return [serialize_course(course) for course in courses]

    @ns.expect(course_model, validate=True)
    @ns.marshal_with(course_model, code=201)
    def post(self) -> dict[str, Any]:
        payload = request.json or {}
        Teacher.query.get_or_404(payload["teacher_id"])
        ClassGroup.query.filter_by(code=payload["group_id"]).first_or_404()
        course = Course(
            name=payload["name"],
            group_id=payload["group_id"],
            size=payload["size"],
            teacher_id=payload["teacher_id"],
            sessions_count=payload["sessions_count"],
            session_minutes=payload["session_minutes"],
            window_start=_parse_date(payload["window_start"]),
            window_end=_parse_date(payload["window_end"]),
        )
        db.session.add(course)
        db.session.flush()
        _sync_requirements(course, payload.get("requirements", []))
        db.session.commit()
        return serialize_course(course), 201


@ns.route("/<int:course_id>")
class CourseResource(Resource):
    @ns.marshal_with(course_model)
    def get(self, course_id: int) -> dict[str, Any]:
        course = Course.query.get_or_404(course_id)
        return serialize_course(course)

    @ns.expect(course_model, validate=True)
    @ns.marshal_with(course_model)
    def put(self, course_id: int) -> dict[str, Any]:
        course = Course.query.get_or_404(course_id)
        payload = request.json or {}
        Teacher.query.get_or_404(payload["teacher_id"])
        ClassGroup.query.filter_by(code=payload["group_id"]).first_or_404()
        course.name = payload["name"]
        course.group_id = payload["group_id"]
        course.size = payload["size"]
        course.teacher_id = payload["teacher_id"]
        course.sessions_count = payload["sessions_count"]
        course.session_minutes = payload["session_minutes"]
        course.window_start = _parse_date(payload["window_start"])
        course.window_end = _parse_date(payload["window_end"])
        _sync_requirements(course, payload.get("requirements", []))
        db.session.commit()
        return serialize_course(course)

    def delete(self, course_id: int) -> tuple[dict[str, str], int]:
        course = Course.query.get_or_404(course_id)
        db.session.delete(course)
        db.session.commit()
        return {"status": "deleted"}, 204


def _sync_requirements(course: Course, payload: list[dict[str, Any]]) -> None:
    course.requirements.clear()
    for item in payload:
        requirement = CourseRequirement(course=course, key=item["key"], value=item["value"])
        course.requirements.append(requirement)
