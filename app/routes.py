from __future__ import annotations

import json
from datetime import datetime, timedelta

from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy.exc import IntegrityError

from . import db
from .models import (
    Course,
    Equipment,
    Room,
    Session,
    Software,
    Teacher,
    default_end_time,
    default_start_time,
)
from .scheduler import START_TIMES, fits_in_windows, generate_schedule

bp = Blueprint("main", __name__)


def _parse_time(value: str | None) -> datetime.time | None:
    if not value:
        return None
    return datetime.strptime(value, "%H:%M").time()


def _parse_date(value: str | None) -> datetime.date | None:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def _parse_datetime(date_str: str, time_str: str) -> datetime:
    return datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")


@bp.route("/", methods=["GET", "POST"])
def dashboard():
    courses = Course.query.order_by(Course.priority.desc()).all()
    teachers = Teacher.query.order_by(Teacher.name).all()
    rooms = Room.query.order_by(Room.name).all()

    if request.method == "POST":
        if request.form.get("form") == "quick-session":
            course_id = int(request.form["course_id"])
            teacher_id = int(request.form["teacher_id"])
            room_id = int(request.form["room_id"])
            date_str = request.form["date"]
            start_time_str = request.form["start_time"]
            course = Course.query.get_or_404(course_id)
            duration_raw = request.form.get("duration")
            duration = int(duration_raw) if duration_raw else course.session_length_hours
            start_dt = _parse_datetime(date_str, start_time_str)
            end_dt = start_dt + timedelta(hours=duration)
            if not fits_in_windows(start_dt.time(), end_dt.time()):
                flash("Le créneau choisi dépasse les fenêtres horaires autorisées", "danger")
                return redirect(url_for("main.dashboard"))

            session = Session(
                course_id=course_id,
                teacher_id=teacher_id,
                room_id=room_id,
                start_time=start_dt,
                end_time=end_dt,
            )
            db.session.add(session)
            db.session.commit()
            flash("Séance créée", "success")
            return redirect(url_for("main.dashboard"))

    events = [session.as_event() for session in Session.query.all()]
    return render_template(
        "dashboard.html",
        courses=courses,
        teachers=teachers,
        rooms=rooms,
        events_json=json.dumps(events, ensure_ascii=False),
        start_times=START_TIMES,
    )


@bp.route("/enseignant", methods=["GET", "POST"])
def teachers_list():
    if request.method == "POST":
        action = request.form.get("form")
        if action == "create":
            teacher = Teacher(
                name=request.form["name"],
                email=request.form.get("email"),
                phone=request.form.get("phone"),
                available_from=_parse_time(request.form.get("available_from")) or default_start_time(),
                available_until=_parse_time(request.form.get("available_until")) or default_end_time(),
                max_hours_per_week=int(request.form.get("max_hours_per_week", 20)),
                unavailable_dates=request.form.get("unavailable_dates"),
                notes=request.form.get("notes"),
            )
            db.session.add(teacher)
            try:
                db.session.commit()
                flash("Enseignant ajouté", "success")
            except IntegrityError:
                db.session.rollback()
                flash("Nom d'enseignant déjà utilisé", "danger")
        elif action == "update":
            teacher = Teacher.query.get_or_404(int(request.form["teacher_id"]))
            teacher.email = request.form.get("email")
            teacher.phone = request.form.get("phone")
            teacher.available_from = _parse_time(request.form.get("available_from")) or teacher.available_from
            teacher.available_until = _parse_time(request.form.get("available_until")) or teacher.available_until
            teacher.max_hours_per_week = int(request.form.get("max_hours_per_week", teacher.max_hours_per_week))
            teacher.unavailable_dates = request.form.get("unavailable_dates")
            teacher.notes = request.form.get("notes")
            db.session.commit()
            flash("Enseignant mis à jour", "success")
        return redirect(url_for("main.teachers_list"))

    teachers = Teacher.query.order_by(Teacher.name).all()
    return render_template("teachers/list.html", teachers=teachers)


@bp.route("/enseignant/<int:teacher_id>", methods=["GET", "POST"])
def teacher_detail(teacher_id: int):
    teacher = Teacher.query.get_or_404(teacher_id)
    courses = Course.query.order_by(Course.name).all()
    assignable_courses = [course for course in courses if teacher not in course.teachers]
    rooms = Room.query.order_by(Room.name).all()

    if request.method == "POST":
        form_name = request.form.get("form")
        if form_name == "update":
            teacher.email = request.form.get("email")
            teacher.phone = request.form.get("phone")
            teacher.available_from = _parse_time(request.form.get("available_from")) or teacher.available_from
            teacher.available_until = _parse_time(request.form.get("available_until")) or teacher.available_until
            teacher.max_hours_per_week = int(request.form.get("max_hours_per_week", teacher.max_hours_per_week))
            teacher.unavailable_dates = request.form.get("unavailable_dates")
            teacher.notes = request.form.get("notes")
            db.session.commit()
            flash("Fiche enseignant mise à jour", "success")
        elif form_name == "assign-course":
            course_id = int(request.form["course_id"])
            course = Course.query.get_or_404(course_id)
            if teacher not in course.teachers:
                course.teachers.append(teacher)
                db.session.commit()
                flash("Enseignant assigné au cours", "success")
        elif form_name == "create-session":
            course_id = int(request.form["course_id"])
            room_id = int(request.form["room_id"])
            course = Course.query.get_or_404(course_id)
            start_dt = _parse_datetime(request.form["date"], request.form["start_time"])
            duration_raw = request.form.get("duration")
            duration = int(duration_raw) if duration_raw else course.session_length_hours
            end_dt = start_dt + timedelta(hours=duration)
            if not fits_in_windows(start_dt.time(), end_dt.time()):
                flash("Le créneau choisi dépasse les fenêtres horaires autorisées", "danger")
                return redirect(url_for("main.teacher_detail", teacher_id=teacher.id))
            session = Session(
                course_id=course_id,
                teacher_id=teacher.id,
                room_id=room_id,
                start_time=start_dt,
                end_time=end_dt,
            )
            db.session.add(session)
            db.session.commit()
            flash("Séance ajoutée", "success")
        return redirect(url_for("main.teacher_detail", teacher_id=teacher_id))

    events = [session.as_event() for session in teacher.sessions]
    default_course_id = None
    if teacher.courses:
        default_course_id = teacher.courses[0].id
    elif courses:
        default_course_id = courses[0].id

    return render_template(
        "teachers/detail.html",
        teacher=teacher,
        courses=courses,
        assignable_courses=assignable_courses,
        rooms=rooms,
        events_json=json.dumps(events, ensure_ascii=False),
        start_times=START_TIMES,
        default_course_id=default_course_id,
    )


@bp.route("/salle", methods=["GET", "POST"])
def rooms_list():
    equipments = Equipment.query.order_by(Equipment.name).all()
    softwares = Software.query.order_by(Software.name).all()

    if request.method == "POST":
        form_name = request.form.get("form")
        if form_name == "create":
            room = Room(
                name=request.form["name"],
                capacity=int(request.form.get("capacity", 20)),
                computers=int(request.form.get("computers", 0)),
                notes=request.form.get("notes"),
            )
            db.session.add(room)
            db.session.commit()
            flash("Salle créée", "success")
        elif form_name == "update":
            room = Room.query.get_or_404(int(request.form["room_id"]))
            room.capacity = int(request.form.get("capacity", room.capacity))
            room.computers = int(request.form.get("computers", room.computers))
            room.notes = request.form.get("notes")
            db.session.commit()
            flash("Salle mise à jour", "success")
        return redirect(url_for("main.rooms_list"))

    rooms = Room.query.order_by(Room.name).all()
    return render_template(
        "rooms/list.html",
        rooms=rooms,
        equipments=equipments,
        softwares=softwares,
    )


@bp.route("/salle/<int:room_id>", methods=["GET", "POST"])
def room_detail(room_id: int):
    room = Room.query.get_or_404(room_id)
    equipments = Equipment.query.order_by(Equipment.name).all()
    softwares = Software.query.order_by(Software.name).all()

    if request.method == "POST":
        form_name = request.form.get("form")
        if form_name == "update":
            room.capacity = int(request.form.get("capacity", room.capacity))
            room.computers = int(request.form.get("computers", room.computers))
            room.notes = request.form.get("notes")
            room.equipments = [
                equipment
                for equipment in (Equipment.query.get(int(eid)) for eid in request.form.getlist("equipments"))
                if equipment is not None
            ]
            room.softwares = [
                software
                for software in (Software.query.get(int(sid)) for sid in request.form.getlist("softwares"))
                if software is not None
            ]
            db.session.commit()
            flash("Salle mise à jour", "success")
        return redirect(url_for("main.room_detail", room_id=room_id))

    events = [session.as_event() for session in room.sessions]
    return render_template(
        "rooms/detail.html",
        room=room,
        equipments=equipments,
        softwares=softwares,
        events_json=json.dumps(events, ensure_ascii=False),
        start_times=START_TIMES,
    )


@bp.route("/matiere", methods=["GET", "POST"])
def courses_list():
    equipments = Equipment.query.order_by(Equipment.name).all()
    softwares = Software.query.order_by(Software.name).all()

    if request.method == "POST":
        form_name = request.form.get("form")
        if form_name == "create":
            course = Course(
                name=request.form["name"],
                description=request.form.get("description"),
                expected_students=int(request.form.get("expected_students", 10)),
                session_length_hours=int(request.form.get("session_length_hours", 2)),
                sessions_required=int(request.form.get("sessions_required", 1)),
                start_date=_parse_date(request.form.get("start_date")),
                end_date=_parse_date(request.form.get("end_date")),
                priority=int(request.form.get("priority", 1)),
                requires_computers=bool(request.form.get("requires_computers")),
            )
            course.equipments = [
                equipment
                for equipment in (Equipment.query.get(int(eid)) for eid in request.form.getlist("equipments"))
                if equipment is not None
            ]
            course.softwares = [
                software
                for software in (Software.query.get(int(sid)) for sid in request.form.getlist("softwares"))
                if software is not None
            ]
            db.session.add(course)
            try:
                db.session.commit()
                flash("Cours créé", "success")
            except IntegrityError:
                db.session.rollback()
                flash("Nom de cours déjà utilisé", "danger")
        return redirect(url_for("main.courses_list"))

    courses = Course.query.order_by(Course.priority.desc()).all()
    return render_template(
        "courses/list.html",
        courses=courses,
        equipments=equipments,
        softwares=softwares,
    )


@bp.route("/matiere/<int:course_id>", methods=["GET", "POST"])
def course_detail(course_id: int):
    course = Course.query.get_or_404(course_id)
    equipments = Equipment.query.order_by(Equipment.name).all()
    softwares = Software.query.order_by(Software.name).all()
    teachers = Teacher.query.order_by(Teacher.name).all()
    rooms = Room.query.order_by(Room.name).all()

    if request.method == "POST":
        form_name = request.form.get("form")
        if form_name == "update":
            course.description = request.form.get("description")
            course.expected_students = int(request.form.get("expected_students", course.expected_students))
            course.session_length_hours = int(request.form.get("session_length_hours", course.session_length_hours))
            course.sessions_required = int(request.form.get("sessions_required", course.sessions_required))
            course.start_date = _parse_date(request.form.get("start_date"))
            course.end_date = _parse_date(request.form.get("end_date"))
            course.priority = int(request.form.get("priority", course.priority))
            course.requires_computers = bool(request.form.get("requires_computers"))
            course.equipments = [
                equipment
                for equipment in (Equipment.query.get(int(eid)) for eid in request.form.getlist("equipments"))
                if equipment is not None
            ]
            course.softwares = [
                software
                for software in (Software.query.get(int(sid)) for sid in request.form.getlist("softwares"))
                if software is not None
            ]
            teacher_ids = {int(tid) for tid in request.form.getlist("teachers")}
            course.teachers = [
                teacher
                for teacher in (Teacher.query.get(tid) for tid in teacher_ids)
                if teacher is not None
            ]
            db.session.commit()
            flash("Cours mis à jour", "success")
        elif form_name == "auto-schedule":
            try:
                created_sessions = generate_schedule(course)
                if created_sessions:
                    db.session.commit()
                    flash(f"{len(created_sessions)} séance(s) générée(s)", "success")
                else:
                    flash("Aucune séance générée", "info")
            except ValueError as exc:
                flash(str(exc), "danger")
        elif form_name == "manual-session":
            teacher_id = int(request.form["teacher_id"])
            room_id = int(request.form["room_id"])
            start_dt = _parse_datetime(request.form["date"], request.form["start_time"])
            duration_raw = request.form.get("duration")
            duration = int(duration_raw) if duration_raw else course.session_length_hours
            end_dt = start_dt + timedelta(hours=duration)
            if not fits_in_windows(start_dt.time(), end_dt.time()):
                flash("Le créneau choisi dépasse les fenêtres horaires autorisées", "danger")
                return redirect(url_for("main.course_detail", course_id=course_id))
            session = Session(
                course_id=course.id,
                teacher_id=teacher_id,
                room_id=room_id,
                start_time=start_dt,
                end_time=end_dt,
            )
            db.session.add(session)
            db.session.commit()
            flash("Séance ajoutée", "success")
        return redirect(url_for("main.course_detail", course_id=course_id))

    events = [session.as_event() for session in course.sessions]
    return render_template(
        "courses/detail.html",
        course=course,
        equipments=equipments,
        softwares=softwares,
        teachers=teachers,
        rooms=rooms,
        events_json=json.dumps(events, ensure_ascii=False),
        start_times=START_TIMES,
    )


@bp.route("/equipement", methods=["GET", "POST"])
def equipment_list():
    if request.method == "POST":
        name = request.form["name"]
        equipment = Equipment(name=name)
        db.session.add(equipment)
        try:
            db.session.commit()
            flash("Équipement ajouté", "success")
        except IntegrityError:
            db.session.rollback()
            flash("Équipement déjà existant", "danger")
        return redirect(url_for("main.equipment_list"))

    equipments = Equipment.query.order_by(Equipment.name).all()
    return render_template("equipment/list.html", equipments=equipments)


@bp.route("/logiciel", methods=["GET", "POST"])
def software_list():
    if request.method == "POST":
        name = request.form["name"]
        software = Software(name=name)
        db.session.add(software)
        try:
            db.session.commit()
            flash("Logiciel ajouté", "success")
        except IntegrityError:
            db.session.rollback()
            flash("Logiciel déjà existant", "danger")
        return redirect(url_for("main.software_list"))

    softwares = Software.query.order_by(Software.name).all()
    return render_template("software/list.html", softwares=softwares)
