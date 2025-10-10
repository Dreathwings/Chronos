from __future__ import annotations

from datetime import datetime

from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from sqlalchemy import select

from .extensions import db
from .models import Course, CourseSession, Room, Teacher
from .scheduling import DAYS, SLOTS, SchedulingError, generate_schedule, group_sessions_by_day

bp = Blueprint("main", __name__)


@bp.app_context_processor
def inject_globals():
    return {
        "DAYS": DAYS,
        "SLOTS": SLOTS,
    }


@bp.route("/")
def index():
    teachers_count = db.session.scalar(select(db.func.count(Teacher.id))) or 0
    rooms_count = db.session.scalar(select(db.func.count(Room.id))) or 0
    courses_count = db.session.scalar(select(db.func.count(Course.id))) or 0
    sessions = CourseSession.query.order_by(
        CourseSession.day_of_week, CourseSession.start_time
    ).all()
    calendar = group_sessions_by_day(sessions)
    return render_template(
        "index.html",
        teachers_count=teachers_count,
        rooms_count=rooms_count,
        courses_count=courses_count,
        sessions_by_day=calendar,
    )


@bp.route("/planifier", methods=["POST"])
def build_schedule():
    try:
        generate_schedule()
        flash("Emploi du temps généré avec succès", "success")
    except SchedulingError as exc:
        flash(str(exc), "danger")
    return redirect(request.referrer or url_for("main.index"))


@bp.route("/enseignant", methods=["GET", "POST"])
def teachers_list():
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip()
        phone_number = request.form.get("phone_number", "").strip() or None
        availability = request.form.get("availability", "").strip() or None
        max_hours = request.form.get("max_weekly_hours", "20").strip()
        try:
            max_weekly_hours = int(max_hours) if max_hours else 20
        except ValueError:
            max_weekly_hours = 20
        max_weekly_hours = max(1, max_weekly_hours)
        if not full_name or not email:
            flash("Le nom et l'email sont obligatoires", "warning")
        else:
            teacher = Teacher(
                full_name=full_name,
                email=email,
                phone_number=phone_number,
                availability=availability,
                max_weekly_hours=max_weekly_hours,
            )
            db.session.add(teacher)
            db.session.commit()
            flash("Enseignant créé", "success")
            return redirect(url_for("main.teachers_list"))
    teachers = Teacher.query.order_by(Teacher.full_name).all()
    return render_template("teachers/list.html", teachers=teachers)


@bp.route("/enseignant/<int:teacher_id>", methods=["GET", "POST"])
def teacher_detail(teacher_id: int):
    teacher = Teacher.query.get_or_404(teacher_id)
    if request.method == "POST":
        method = request.form.get("_method", "").upper()
        if method == "DELETE":
            db.session.delete(teacher)
            db.session.commit()
            flash("Enseignant supprimé", "info")
            return redirect(url_for("main.teachers_list"))
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip()
        teacher.phone_number = request.form.get("phone_number", "").strip() or None
        teacher.availability = request.form.get("availability", "").strip() or None
        max_hours_raw = request.form.get("max_weekly_hours", "20") or "20"
        try:
            teacher.max_weekly_hours = int(max_hours_raw)
        except ValueError:
            teacher.max_weekly_hours = 20
        teacher.max_weekly_hours = max(1, teacher.max_weekly_hours)
        if not full_name or not email:
            flash("Le nom et l'email sont obligatoires", "warning")
        else:
            teacher.full_name = full_name
            teacher.email = email
            db.session.commit()
            flash("Enseignant mis à jour", "success")
            return redirect(url_for("main.teacher_detail", teacher_id=teacher.id))
    sessions = CourseSession.query.filter_by(teacher_id=teacher.id).order_by(
        CourseSession.day_of_week, CourseSession.start_time
    )
    return render_template(
        "teachers/detail.html",
        teacher=teacher,
        sessions_by_day=group_sessions_by_day(sessions),
    )


@bp.route("/salle", methods=["GET", "POST"])
def rooms_list():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        capacity_raw = request.form.get("capacity", "0") or "0"
        try:
            capacity = int(capacity_raw)
        except ValueError:
            capacity = 0
        capacity = max(0, capacity)
        location = request.form.get("location", "").strip() or None
        equipments = request.form.get("equipments", "").strip() or None
        has_computers = request.form.get("has_computers") == "on"
        if not name:
            flash("Le nom de la salle est obligatoire", "warning")
        else:
            room = Room(
                name=name,
                capacity=capacity or 20,
                location=location,
                equipments=equipments,
                has_computers=has_computers,
            )
            db.session.add(room)
            db.session.commit()
            flash("Salle enregistrée", "success")
            return redirect(url_for("main.rooms_list"))
    rooms = Room.query.order_by(Room.name).all()
    return render_template("rooms/list.html", rooms=rooms)


@bp.route("/salle/<int:room_id>", methods=["GET", "POST"])
def room_detail(room_id: int):
    room = Room.query.get_or_404(room_id)
    if request.method == "POST":
        method = request.form.get("_method", "").upper()
        if method == "DELETE":
            db.session.delete(room)
            db.session.commit()
            flash("Salle supprimée", "info")
            return redirect(url_for("main.rooms_list"))
        room.name = request.form.get("name", "").strip() or room.name
        capacity_raw = request.form.get("capacity", room.capacity)
        try:
            room.capacity = int(capacity_raw)
        except (TypeError, ValueError):
            pass
        room.capacity = max(0, room.capacity)
        room.location = request.form.get("location", "").strip() or None
        room.equipments = request.form.get("equipments", "").strip() or None
        room.has_computers = request.form.get("has_computers") == "on"
        db.session.commit()
        flash("Salle mise à jour", "success")
        return redirect(url_for("main.room_detail", room_id=room.id))
    sessions = CourseSession.query.filter_by(room_id=room.id).order_by(
        CourseSession.day_of_week, CourseSession.start_time
    )
    return render_template(
        "rooms/detail.html",
        room=room,
        sessions_by_day=group_sessions_by_day(sessions),
    )


@bp.route("/matiere", methods=["GET", "POST"])
def courses_list():
    teachers = Teacher.query.order_by(Teacher.full_name).all()
    rooms = Room.query.order_by(Room.name).all()
    if request.method == "POST":
        code = request.form.get("code", "").strip()
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip() or None
        try:
            duration = int(request.form.get("duration_hours", "1") or 1)
        except ValueError:
            duration = 1
        duration = max(1, duration)
        try:
            group_size = int(request.form.get("group_size", "10") or 10)
        except ValueError:
            group_size = 10
        group_size = max(1, group_size)
        required_equipments = request.form.get("required_equipments", "").strip() or None
        try:
            priority = int(request.form.get("priority", "1") or 1)
        except ValueError:
            priority = 1
        priority = max(1, min(priority, 10))
        teacher_id = request.form.get("teacher_id") or None
        room_id = request.form.get("room_id") or None
        start_date_raw = request.form.get("start_date") or None
        end_date_raw = request.form.get("end_date") or None
        if not code or not title:
            flash("Le code et le titre sont obligatoires", "warning")
        else:
            course = Course(
                code=code,
                title=title,
                description=description,
                duration_hours=duration,
                group_size=group_size,
                required_equipments=required_equipments,
                priority=priority,
            )
            if teacher_id:
                course.teacher = Teacher.query.get(int(teacher_id))
            if room_id:
                course.room = Room.query.get(int(room_id))
            if start_date_raw:
                course.start_date = datetime.strptime(start_date_raw, "%Y-%m-%d").date()
            if end_date_raw:
                course.end_date = datetime.strptime(end_date_raw, "%Y-%m-%d").date()
            db.session.add(course)
            db.session.commit()
            flash("Cours créé", "success")
            return redirect(url_for("main.courses_list"))
    courses = Course.query.order_by(Course.code).all()
    return render_template(
        "courses/list.html",
        courses=courses,
        teachers=teachers,
        rooms=rooms,
    )


@bp.route("/matiere/<int:course_id>", methods=["GET", "POST"])
def course_detail(course_id: int):
    course = Course.query.get_or_404(course_id)
    teachers = Teacher.query.order_by(Teacher.full_name).all()
    rooms = Room.query.order_by(Room.name).all()
    if request.method == "POST":
        method = request.form.get("_method", "").upper()
        if method == "DELETE":
            db.session.delete(course)
            db.session.commit()
            flash("Cours supprimé", "info")
            return redirect(url_for("main.courses_list"))
        course.code = request.form.get("code", course.code).strip() or course.code
        course.title = request.form.get("title", course.title).strip() or course.title
        course.description = request.form.get("description", "").strip() or None
        try:
            course.duration_hours = int(
                request.form.get("duration_hours", course.duration_hours) or course.duration_hours
            )
        except ValueError:
            pass
        course.duration_hours = max(1, course.duration_hours)
        try:
            course.group_size = int(
                request.form.get("group_size", course.group_size) or course.group_size
            )
        except ValueError:
            pass
        course.group_size = max(1, course.group_size)
        course.required_equipments = request.form.get("required_equipments", "").strip() or None
        try:
            course.priority = int(request.form.get("priority", course.priority) or course.priority)
        except ValueError:
            pass
        course.priority = max(1, min(course.priority, 10))
        teacher_id = request.form.get("teacher_id") or None
        room_id = request.form.get("room_id") or None
        start_date_raw = request.form.get("start_date") or None
        end_date_raw = request.form.get("end_date") or None
        course.teacher = Teacher.query.get(int(teacher_id)) if teacher_id else None
        course.room = Room.query.get(int(room_id)) if room_id else None
        course.start_date = (
            datetime.strptime(start_date_raw, "%Y-%m-%d").date() if start_date_raw else None
        )
        course.end_date = (
            datetime.strptime(end_date_raw, "%Y-%m-%d").date() if end_date_raw else None
        )
        db.session.commit()
        flash("Cours mis à jour", "success")
        return redirect(url_for("main.course_detail", course_id=course.id))
    sessions = CourseSession.query.filter_by(course_id=course.id).order_by(
        CourseSession.day_of_week, CourseSession.start_time
    )
    return render_template(
        "courses/detail.html",
        course=course,
        teachers=teachers,
        rooms=rooms,
        sessions_by_day=group_sessions_by_day(sessions),
    )
