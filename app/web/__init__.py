"""Web UI blueprint for Chronos administration pages."""
from __future__ import annotations

from datetime import date, datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..models import ClassGroup, Course, CourseRequirement, Room, RoomEquipment, Teacher


web_bp = Blueprint("web", __name__)


@web_bp.app_template_filter("datetime")
def format_datetime(value: datetime | None, fmt: str = "%d/%m/%Y") -> str:
    if value is None:
        return ""
    if isinstance(value, (datetime, date)):
        return value.strftime(fmt)
    return value


@web_bp.route("/")
def dashboard() -> str:
    stats = {
        "teachers": Teacher.query.count(),
        "rooms": Room.query.count(),
        "classes": ClassGroup.query.count(),
        "courses": Course.query.count(),
    }
    latest_courses = Course.query.order_by(Course.id.desc()).limit(5).all()
    return render_template("dashboard.html", stats=stats, latest_courses=latest_courses)


@web_bp.route("/rooms", methods=["GET", "POST"])
def manage_rooms() -> str:
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        capacity = request.form.get("capacity", "").strip()
        building = request.form.get("building", "").strip() or None
        equipment_lines = request.form.get("equipment", "").strip().splitlines()
        if not name or not capacity:
            flash("Nom et capacité sont obligatoires", "danger")
        else:
            try:
                capacity_value = int(capacity)
            except ValueError:
                flash("La capacité doit être un nombre", "danger")
            else:
                room = Room(name=name, capacity=capacity_value, building=building)
                for line in equipment_lines:
                    if not line:
                        continue
                    if "=" not in line:
                        flash("Format équipement invalide (clé=valeur)", "danger")
                        db.session.rollback()
                        break
                    key, value = [part.strip() for part in line.split("=", 1)]
                    room.equipment.append(RoomEquipment(key=key, value=value))
                else:
                    db.session.add(room)
                    try:
                        db.session.commit()
                    except IntegrityError:
                        db.session.rollback()
                        flash("Une salle avec ce nom existe déjà", "danger")
                    else:
                        flash("Salle créée", "success")
                        return redirect(url_for("web.manage_rooms"))
    rooms = Room.query.order_by(Room.name).all()
    return render_template("rooms.html", rooms=rooms)


@web_bp.post("/rooms/<int:room_id>/delete")
def delete_room(room_id: int):
    room = Room.query.get_or_404(room_id)
    if room.assignments:
        flash("Impossible de supprimer une salle planifiée", "danger")
    else:
        db.session.delete(room)
        db.session.commit()
        flash("Salle supprimée", "success")
    return redirect(url_for("web.manage_rooms"))


@web_bp.route("/teachers", methods=["GET", "POST"])
def manage_teachers() -> str:
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        load = request.form.get("max_weekly_load_hrs", "").strip()
        if not name or not load:
            flash("Nom et charge hebdomadaire sont obligatoires", "danger")
        else:
            try:
                load_value = int(load)
            except ValueError:
                flash("La charge doit être un nombre d'heures", "danger")
            else:
                teacher = Teacher(name=name, max_weekly_load_hrs=load_value)
                db.session.add(teacher)
                try:
                    db.session.commit()
                except IntegrityError:
                    db.session.rollback()
                    flash("Un enseignant avec ce nom existe déjà", "danger")
                else:
                    flash("Enseignant créé", "success")
                    return redirect(url_for("web.manage_teachers"))
    teachers = Teacher.query.order_by(Teacher.name).all()
    return render_template("teachers.html", teachers=teachers)


@web_bp.post("/teachers/<int:teacher_id>/delete")
def delete_teacher(teacher_id: int):
    teacher = Teacher.query.get_or_404(teacher_id)
    if teacher.courses:
        flash("Impossible de supprimer un enseignant lié à des cours", "danger")
    else:
        db.session.delete(teacher)
        db.session.commit()
        flash("Enseignant supprimé", "success")
    return redirect(url_for("web.manage_teachers"))


@web_bp.route("/classes", methods=["GET", "POST"])
def manage_classes() -> str:
    if request.method == "POST":
        code = request.form.get("code", "").strip()
        name = request.form.get("name", "").strip() or code
        size = request.form.get("size", "").strip()
        notes = request.form.get("notes", "").strip() or None
        if not code or not size:
            flash("Le code et l'effectif sont obligatoires", "danger")
        else:
            try:
                size_value = int(size)
            except ValueError:
                flash("L'effectif doit être un nombre", "danger")
            else:
                class_group = ClassGroup(code=code, name=name, size=size_value, notes=notes)
                db.session.add(class_group)
                try:
                    db.session.commit()
                except IntegrityError:
                    db.session.rollback()
                    flash("Cette classe existe déjà", "danger")
                else:
                    flash("Classe créée", "success")
                    return redirect(url_for("web.manage_classes"))
    classes = ClassGroup.query.order_by(ClassGroup.code).all()
    return render_template("classes.html", classes=classes)


@web_bp.post("/classes/<int:class_id>/delete")
def delete_class(class_id: int):
    class_group = ClassGroup.query.get_or_404(class_id)
    if class_group.courses:
        flash("Impossible de supprimer une classe liée à des cours", "danger")
    else:
        db.session.delete(class_group)
        db.session.commit()
        flash("Classe supprimée", "success")
    return redirect(url_for("web.manage_classes"))


def _parse_requirements(raw: str) -> list[tuple[str, str]]:
    requirements: list[tuple[str, str]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        if "=" not in line:
            raise ValueError("Format des exigences invalide (clé=valeur)")
        key, value = [item.strip() for item in line.split("=", 1)]
        requirements.append((key, value))
    return requirements


@web_bp.route("/courses", methods=["GET", "POST"])
def manage_courses() -> str:
    teachers = Teacher.query.order_by(Teacher.name).all()
    class_groups = ClassGroup.query.order_by(ClassGroup.code).all()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        group_id = request.form.get("group_id", "").strip()
        size = request.form.get("size", "").strip()
        teacher_id = request.form.get("teacher_id", "").strip()
        sessions_count = request.form.get("sessions_count", "").strip()
        session_minutes = request.form.get("session_minutes", "").strip()
        window_start = request.form.get("window_start", "").strip()
        window_end = request.form.get("window_end", "").strip()
        requirements_raw = request.form.get("requirements", "")

        errors: list[str] = []
        if not name:
            errors.append("Le nom du cours est obligatoire")
        if not group_id:
            errors.append("La classe est obligatoire")
        if not teacher_id:
            errors.append("L'enseignant est obligatoire")
        try:
            size_value = int(size)
        except ValueError:
            errors.append("L'effectif du cours doit être un nombre")
        else:
            if size_value <= 0:
                errors.append("L'effectif doit être positif")
        try:
            sessions_value = int(sessions_count)
            minutes_value = int(session_minutes)
        except ValueError:
            errors.append("Sessions et durée doivent être numériques")
        else:
            if sessions_value <= 0 or minutes_value <= 0:
                errors.append("Sessions et durée doivent être positifs")
        try:
            window_start_value = datetime.strptime(window_start, "%Y-%m-%d").date()
            window_end_value = datetime.strptime(window_end, "%Y-%m-%d").date()
        except ValueError:
            errors.append("Dates invalides (format AAAA-MM-JJ)")
        else:
            if window_end_value < window_start_value:
                errors.append("La date de fin doit être postérieure au début")
        try:
            requirements = _parse_requirements(requirements_raw)
        except ValueError as exc:
            errors.append(str(exc))
        try:
            teacher_id_value = int(teacher_id)
        except (TypeError, ValueError):
            errors.append("Identifiant d'enseignant invalide")
            teacher_id_value = None
        else:
            if not Teacher.query.get(teacher_id_value):
                errors.append("Enseignant inconnu")

        class_group = None
        if group_id:
            class_group = ClassGroup.query.filter_by(code=group_id).first()
            if class_group is None:
                errors.append("Classe inconnue")

        if errors:
            for message in errors:
                flash(message, "danger")
        else:
            course = Course(
                name=name,
                group_id=group_id,
                size=size_value,
                teacher_id=teacher_id_value,
                sessions_count=sessions_value,
                session_minutes=minutes_value,
                window_start=window_start_value,
                window_end=window_end_value,
            )
            course.class_group = class_group
            for key, value in requirements:
                course.requirements.append(CourseRequirement(key=key, value=value))
            db.session.add(course)
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                flash("Erreur lors de l'enregistrement du cours", "danger")
            else:
                flash("Cours créé", "success")
                return redirect(url_for("web.manage_courses"))
    courses = Course.query.order_by(Course.name).all()
    return render_template(
        "courses.html",
        courses=courses,
        teachers=teachers,
        class_groups=class_groups,
    )


@web_bp.post("/courses/<int:course_id>/delete")
def delete_course(course_id: int):
    course = Course.query.get_or_404(course_id)
    if course.assignments:
        flash("Impossible de supprimer un cours planifié", "danger")
    else:
        db.session.delete(course)
        db.session.commit()
        flash("Cours supprimé", "success")
    return redirect(url_for("web.manage_courses"))
