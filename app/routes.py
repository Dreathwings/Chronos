from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from flask import Blueprint, flash, redirect, render_template, request, url_for

from .extensions import db
from .models import Course, Room, Teacher
from .scheduler import apply_schedule

bp = Blueprint("main", __name__)


def get_calendar_entries(courses: list[Course]) -> list[dict[str, Any]]:
    return [course.to_calendar_dict() for course in sorted(courses, key=lambda c: c.start_time)]


@bp.route("/")
def index() -> str:
    teachers = Teacher.query.order_by(Teacher.full_name).all()
    rooms = Room.query.order_by(Room.name).all()
    courses = Course.query.order_by(Course.start_time).all()
    return render_template(
        "index.html",
        teachers=teachers,
        rooms=rooms,
        courses=courses,
    )


@bp.route("/optimize", methods=["POST"])
def optimize() -> str:
    apply_schedule()
    flash("Planning optimisé avec succès", "success")
    return redirect(request.referrer or url_for("main.index"))


@bp.route("/enseignant")
def list_teachers() -> str:
    teachers = Teacher.query.order_by(Teacher.full_name).all()
    return render_template("enseignants/list.html", teachers=teachers)


@bp.route("/enseignant/new", methods=["GET", "POST"])
def create_teacher() -> str:
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip()
        department = request.form.get("department", "").strip() or None
        if not full_name or not email:
            flash("Le nom complet et l'email sont obligatoires", "danger")
        else:
            teacher = Teacher(full_name=full_name, email=email, department=department)
            db.session.add(teacher)
            db.session.commit()
            flash("Enseignant créé", "success")
            return redirect(url_for("main.list_teachers"))
    return render_template("enseignants/form.html", teacher=None)


@bp.route("/enseignant/<int:teacher_id>")
def show_teacher(teacher_id: int) -> str:
    teacher = Teacher.query.get_or_404(teacher_id)
    courses = Course.query.filter_by(teacher_id=teacher.id).order_by(Course.start_time).all()
    return render_template(
        "enseignants/detail.html",
        teacher=teacher,
        courses=courses,
        calendar=get_calendar_entries(courses),
    )


@bp.route("/enseignant/<int:teacher_id>/edit", methods=["GET", "POST"])
def edit_teacher(teacher_id: int) -> str:
    teacher = Teacher.query.get_or_404(teacher_id)
    if request.method == "POST":
        teacher.full_name = request.form.get("full_name", teacher.full_name)
        teacher.email = request.form.get("email", teacher.email)
        teacher.department = request.form.get("department") or None
        db.session.commit()
        flash("Enseignant mis à jour", "success")
        return redirect(url_for("main.show_teacher", teacher_id=teacher.id))
    return render_template("enseignants/form.html", teacher=teacher)


@bp.route("/enseignant/<int:teacher_id>/delete", methods=["POST"])
def delete_teacher(teacher_id: int) -> str:
    teacher = Teacher.query.get_or_404(teacher_id)
    db.session.delete(teacher)
    db.session.commit()
    flash("Enseignant supprimé", "info")
    return redirect(url_for("main.list_teachers"))


@bp.route("/salle")
def list_rooms() -> str:
    rooms = Room.query.order_by(Room.name).all()
    return render_template("salles/list.html", rooms=rooms)


@bp.route("/salle/new", methods=["GET", "POST"])
def create_room() -> str:
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        capacity = request.form.get("capacity", 0)
        equipments = request.form.get("equipments", "").strip() or None
        has_computers = bool(request.form.get("has_computers"))
        if not name:
            flash("Le nom est obligatoire", "danger")
        else:
            room = Room(
                name=name,
                capacity=int(capacity or 0),
                equipments=equipments,
                has_computers=has_computers,
            )
            db.session.add(room)
            db.session.commit()
            flash("Salle créée", "success")
            return redirect(url_for("main.list_rooms"))
    return render_template("salles/form.html", room=None)


@bp.route("/salle/<int:room_id>")
def show_room(room_id: int) -> str:
    room = Room.query.get_or_404(room_id)
    courses = Course.query.filter_by(room_id=room.id).order_by(Course.start_time).all()
    return render_template(
        "salles/detail.html",
        room=room,
        courses=courses,
        calendar=get_calendar_entries(courses),
    )


@bp.route("/salle/<int:room_id>/edit", methods=["GET", "POST"])
def edit_room(room_id: int) -> str:
    room = Room.query.get_or_404(room_id)
    if request.method == "POST":
        room.name = request.form.get("name", room.name)
        room.capacity = int(request.form.get("capacity", room.capacity))
        room.equipments = request.form.get("equipments") or None
        room.has_computers = bool(request.form.get("has_computers"))
        db.session.commit()
        flash("Salle mise à jour", "success")
        return redirect(url_for("main.show_room", room_id=room.id))
    return render_template("salles/form.html", room=room)


@bp.route("/salle/<int:room_id>/delete", methods=["POST"])
def delete_room(room_id: int) -> str:
    room = Room.query.get_or_404(room_id)
    db.session.delete(room)
    db.session.commit()
    flash("Salle supprimée", "info")
    return redirect(url_for("main.list_rooms"))


@bp.route("/matiere")
def list_courses() -> str:
    courses = Course.query.order_by(Course.start_time).all()
    return render_template("matieres/list.html", courses=courses)


@bp.route("/matiere/new", methods=["GET", "POST"])
def create_course() -> str:
    teachers = Teacher.query.order_by(Teacher.full_name).all()
    rooms = Room.query.order_by(Room.name).all()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        teacher_id = request.form.get("teacher_id")
        room_id = request.form.get("room_id") or None
        group_name = request.form.get("group_name", "A1").strip()
        duration_hours = int(request.form.get("duration_hours", 1))
        priority = int(request.form.get("priority", 1))
        software_required = request.form.get("software_required", "").strip() or None
        start_date = request.form.get("start_date")

        if not (name and teacher_id and start_date):
            flash("Les champs nom, enseignant et date de début sont obligatoires", "danger")
        else:
            start = datetime.fromisoformat(start_date)
            end = start + timedelta(hours=duration_hours)
            course = Course(
                name=name,
                teacher_id=int(teacher_id),
                room_id=int(room_id) if room_id else None,
                group_name=group_name,
                duration_hours=duration_hours,
                priority=priority,
                software_required=software_required,
                start_time=start,
                end_time=end,
            )
            db.session.add(course)
            db.session.commit()
            flash("Cours créé", "success")
            return redirect(url_for("main.list_courses"))
    return render_template("matieres/form.html", teachers=teachers, rooms=rooms, course=None)


@bp.route("/matiere/<int:course_id>")
def show_course(course_id: int) -> str:
    course = Course.query.get_or_404(course_id)
    return render_template(
        "matieres/detail.html",
        course=course,
    )


@bp.route("/matiere/<int:course_id>/edit", methods=["GET", "POST"])
def edit_course(course_id: int) -> str:
    course = Course.query.get_or_404(course_id)
    teachers = Teacher.query.order_by(Teacher.full_name).all()
    rooms = Room.query.order_by(Room.name).all()
    if request.method == "POST":
        course.name = request.form.get("name", course.name)
        course.group_name = request.form.get("group_name", course.group_name)
        course.teacher_id = int(request.form.get("teacher_id", course.teacher_id))
        room_id = request.form.get("room_id") or None
        course.room_id = int(room_id) if room_id else None
        course.duration_hours = int(request.form.get("duration_hours", course.duration_hours))
        course.priority = int(request.form.get("priority", course.priority))
        course.software_required = request.form.get("software_required") or None
        start_date = request.form.get("start_date")
        if start_date:
            start = datetime.fromisoformat(start_date)
            course.start_time = start
            course.end_time = start + timedelta(hours=course.duration_hours)
        db.session.commit()
        flash("Cours mis à jour", "success")
        return redirect(url_for("main.show_course", course_id=course.id))
    return render_template("matieres/form.html", course=course, teachers=teachers, rooms=rooms)


@bp.route("/matiere/<int:course_id>/delete", methods=["POST"])
def delete_course(course_id: int) -> str:
    course = Course.query.get_or_404(course_id)
    db.session.delete(course)
    db.session.commit()
    flash("Cours supprimé", "info")
    return redirect(url_for("main.list_courses"))
