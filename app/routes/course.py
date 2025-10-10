"""Course management routes."""
from __future__ import annotations

from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy.orm import joinedload

from .. import db
from ..models import Course, CourseSession, Material, Room, Software, Teacher

bp = Blueprint("course", __name__)


@bp.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description") or None
        sessions_required = int(request.form.get("sessions_required", 1))
        duration = int(request.form.get("session_duration_hours", 2))
        priority = int(request.form.get("priority", 1))
        start_date = request.form.get("start_date") or None
        end_date = request.form.get("end_date") or None
        materials_raw = request.form.get("materials", "")
        software_raw = request.form.get("software", "")

        if not title:
            flash("Le titre du cours est obligatoire", "danger")
        else:
            course = Course(
                title=title,
                description=description,
                sessions_required=sessions_required,
                session_duration_hours=duration,
                priority=priority,
                start_date=datetime.strptime(start_date, "%Y-%m-%d").date()
                if start_date
                else None,
                end_date=datetime.strptime(end_date, "%Y-%m-%d").date()
                if end_date
                else None,
            )
            course.materials = _find_or_create_materials(materials_raw)
            course.software = _find_or_create_software(software_raw)
            db.session.add(course)
            db.session.commit()
            flash("Cours créé", "success")
            return redirect(url_for("course.index"))

    courses = Course.query.order_by(Course.title).all()
    return render_template("matiere/index.html", courses=courses)


@bp.route("/<int:course_id>", methods=["GET", "POST"])
def detail(course_id: int):
    course = (
        Course.query.options(
            joinedload(Course.materials),
            joinedload(Course.software),
            joinedload(Course.sessions).joinedload(CourseSession.teacher),
            joinedload(Course.sessions).joinedload(CourseSession.room),
        )
        .filter_by(id=course_id)
        .first_or_404()
    )

    teachers = Teacher.query.order_by(Teacher.last_name, Teacher.first_name).all()
    rooms = Room.query.order_by(Room.name).all()

    if request.method == "POST":
        action = request.form.get("action")
        if action == "update_course":
            course.title = request.form.get("title", course.title)
            course.description = request.form.get("description") or None
            course.sessions_required = int(
                request.form.get("sessions_required", course.sessions_required)
            )
            course.session_duration_hours = int(
                request.form.get("session_duration_hours", course.session_duration_hours)
            )
            course.priority = int(request.form.get("priority", course.priority))
            start_date = request.form.get("start_date")
            end_date = request.form.get("end_date")
            course.start_date = (
                datetime.strptime(start_date, "%Y-%m-%d").date() if start_date else None
            )
            course.end_date = (
                datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else None
            )
            course.materials = _find_or_create_materials(
                request.form.get("materials", "")
            )
            course.software = _find_or_create_software(
                request.form.get("software", "")
            )
            db.session.commit()
            flash("Cours mis à jour", "success")
            return redirect(url_for("course.detail", course_id=course.id))

        if action == "add_session":
            start_date = request.form.get("start_date")
            start_time = request.form.get("start_time")
            duration = int(request.form.get("duration_hours", course.session_duration_hours))
            teacher_id = request.form.get("teacher_id")
            room_id = request.form.get("room_id")
            if start_date and start_time:
                start_dt = datetime.fromisoformat(f"{start_date}T{start_time}")
                session = CourseSession(
                    course=course,
                    teacher_id=int(teacher_id) if teacher_id else None,
                    room_id=int(room_id) if room_id else None,
                    start_datetime=start_dt,
                    end_datetime=start_dt + _hours_to_delta(duration),
                )
                db.session.add(session)
                db.session.commit()
                flash("Séance ajoutée", "success")
            else:
                flash("Date et heure obligatoires", "danger")
            return redirect(url_for("course.detail", course_id=course.id))

    events = [session.as_fullcalendar_event() for session in course.sessions]
    return render_template(
        "matiere/detail.html",
        course=course,
        events=events,
        teachers=teachers,
        rooms=rooms,
    )


def _find_or_create_materials(raw_values: str) -> list[Material]:
    names = {name.strip() for name in raw_values.split(",") if name.strip()}
    materials: list[Material] = []
    for name in names:
        material = Material.query.filter_by(name=name).first()
        if not material:
            material = Material(name=name)
            db.session.add(material)
        materials.append(material)
    return materials


def _find_or_create_software(raw_values: str) -> list[Software]:
    names = {name.strip() for name in raw_values.split(",") if name.strip()}
    softwares: list[Software] = []
    for name in names:
        software = Software.query.filter_by(name=name).first()
        if not software:
            software = Software(name=name)
            db.session.add(software)
        softwares.append(software)
    return softwares


def _hours_to_delta(hours: int):
    from datetime import timedelta

    return timedelta(hours=hours)
