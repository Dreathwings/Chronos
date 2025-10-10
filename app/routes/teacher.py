"""Teacher management routes."""
from __future__ import annotations

from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy.orm import joinedload

from .. import db
from ..models import Teacher, TeacherAvailability, TeacherUnavailability

bp = Blueprint("teacher", __name__)


@bp.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        first_name = request.form.get("first_name", "").strip()
        last_name = request.form.get("last_name", "").strip()
        email = request.form.get("email", "").strip()
        max_hours = request.form.get("max_hours_per_week", "20").strip()
        notes = request.form.get("notes", "").strip() or None

        if not all([first_name, last_name, email]):
            flash("Les champs prénom, nom et email sont obligatoires", "danger")
        else:
            teacher = Teacher(
                first_name=first_name,
                last_name=last_name,
                email=email,
                max_hours_per_week=int(max_hours or 20),
                notes=notes,
            )
            db.session.add(teacher)
            db.session.commit()
            flash("Enseignant créé", "success")
            return redirect(url_for("teacher.index"))

    teachers = Teacher.query.order_by(Teacher.last_name, Teacher.first_name).all()
    return render_template("enseignant/index.html", teachers=teachers)


@bp.route("/<int:teacher_id>", methods=["GET", "POST"])
def detail(teacher_id: int):
    teacher = (
        Teacher.query.options(
            joinedload(Teacher.availabilities),
            joinedload(Teacher.unavailabilities),
            joinedload(Teacher.sessions),
        )
        .filter_by(id=teacher_id)
        .first_or_404()
    )

    if request.method == "POST":
        if request.form.get("action") == "update_teacher":
            teacher.first_name = request.form.get("first_name", teacher.first_name)
            teacher.last_name = request.form.get("last_name", teacher.last_name)
            teacher.email = request.form.get("email", teacher.email)
            teacher.max_hours_per_week = int(
                request.form.get("max_hours_per_week", teacher.max_hours_per_week)
            )
            teacher.notes = request.form.get("notes") or None
            db.session.commit()
            flash("Informations mises à jour", "success")
            return redirect(url_for("teacher.detail", teacher_id=teacher.id))

        if request.form.get("action") == "add_availability":
            weekday = int(request.form.get("weekday", "0"))
            start_time = request.form.get("start_time")
            end_time = request.form.get("end_time")
            if start_time and end_time:
                availability = TeacherAvailability(
                    teacher=teacher,
                    weekday=weekday,
                    start_time=datetime.strptime(start_time, "%H:%M").time(),
                    end_time=datetime.strptime(end_time, "%H:%M").time(),
                )
                db.session.add(availability)
                db.session.commit()
                flash("Disponibilité ajoutée", "success")
            else:
                flash("Heures de disponibilité invalides", "danger")
            return redirect(url_for("teacher.detail", teacher_id=teacher.id))

        if request.form.get("action") == "add_unavailability":
            date_value = request.form.get("date")
            reason = request.form.get("reason") or None
            if date_value:
                unavailability = TeacherUnavailability(
                    teacher=teacher,
                    date=datetime.strptime(date_value, "%Y-%m-%d").date(),
                    reason=reason,
                )
                db.session.add(unavailability)
                db.session.commit()
                flash("Indisponibilité ajoutée", "success")
            else:
                flash("Date invalide", "danger")
            return redirect(url_for("teacher.detail", teacher_id=teacher.id))

    events = [session.as_fullcalendar_event() for session in teacher.sessions]
    return render_template(
        "enseignant/detail.html",
        teacher=teacher,
        events=events,
    )
