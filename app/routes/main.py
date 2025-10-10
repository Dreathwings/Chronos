"""Dashboard routes."""
from __future__ import annotations

from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy.orm import joinedload

from .. import db
from ..models import Course, CourseSession, Room, Teacher

bp = Blueprint("main", __name__)


@bp.route("/", methods=["GET", "POST"])
def dashboard():
    courses = Course.query.order_by(Course.title).all()
    teachers = Teacher.query.order_by(Teacher.last_name, Teacher.first_name).all()
    rooms = Room.query.order_by(Room.name).all()

    if request.method == "POST":
        try:
            course_id = int(request.form["course_id"])
            teacher_id = request.form.get("teacher_id")
            room_id = request.form.get("room_id")
            start_date = request.form["start_date"]
            start_time = request.form["start_time"]
            duration_hours = int(request.form.get("duration_hours", "2"))
        except (KeyError, ValueError):
            flash("Formulaire incomplet pour planifier la séance", "danger")
            return redirect(url_for("main.dashboard"))

        course = Course.query.get_or_404(course_id)
        teacher = Teacher.query.get(int(teacher_id)) if teacher_id else None
        room = Room.query.get(int(room_id)) if room_id else None

        start_dt = datetime.fromisoformat(f"{start_date}T{start_time}")
        end_dt = start_dt + _hours_to_delta(duration_hours)

        session = CourseSession(
            course=course,
            teacher=teacher,
            room=room,
            start_datetime=start_dt,
            end_datetime=end_dt,
        )
        db.session.add(session)
        db.session.commit()
        flash("Séance planifiée", "success")
        return redirect(url_for("main.dashboard"))

    sessions = (
        CourseSession.query.options(
            joinedload(CourseSession.course),
            joinedload(CourseSession.teacher),
            joinedload(CourseSession.room),
        )
        .order_by(CourseSession.start_datetime)
        .all()
    )
    events = [session.as_fullcalendar_event() for session in sessions]

    return render_template(
        "dashboard.html",
        courses=courses,
        teachers=teachers,
        rooms=rooms,
        events=events,
    )


def _hours_to_delta(hours: int):
    from datetime import timedelta

    return timedelta(hours=hours)
