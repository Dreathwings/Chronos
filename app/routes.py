from __future__ import annotations

from datetime import datetime, timedelta

from flask import Blueprint, flash, jsonify, redirect, render_template, url_for

from . import db
from .forms import (
    CourseForm,
    MaterialForm,
    QuickPlanForm,
    RoomForm,
    SessionForm,
    SoftwareForm,
    TeacherAvailabilityForm,
    TeacherForm,
    TeacherUnavailabilityForm,
)
from .models import (
    Course,
    CourseSession,
    Material,
    Room,
    Software,
    Teacher,
    TeacherAvailability,
    TeacherUnavailability,
)
from .scheduler import SLOT_DEFINITION, PlanningError, plan_sessions


main_bp = Blueprint("main", __name__)


def _slot_choices() -> list[tuple[str, str]]:
    choices: list[tuple[str, str]] = []
    for idx, (start_time, end_time) in enumerate(SLOT_DEFINITION):
        label = f"{start_time.strftime('%H:%M')} - {end_time.strftime('%H:%M')}"
        choices.append((str(idx), label))
    return choices


def _apply_materials(entity, material_ids: list[int]) -> None:
    entity.materials = Material.query.filter(Material.id.in_(material_ids)).all() if material_ids else []


def _apply_softwares(entity, software_ids: list[int]) -> None:
    entity.softwares = Software.query.filter(Software.id.in_(software_ids)).all() if software_ids else []


def _serialize_session(session: CourseSession) -> dict[str, str]:
    return {
        "id": session.id,
        "title": session.course.title,
        "start": session.start.isoformat(),
        "end": session.end.isoformat(),
        "teacher": session.teacher.full_name if session.teacher else None,
        "room": session.room.name if session.room else None,
        "course": session.course.title,
    }


@main_bp.route("/", methods=["GET", "POST"])
def dashboard():
    quick_plan_form = QuickPlanForm()
    session_form = SessionForm()
    session_form.course_id.choices = [(c.id, c.title) for c in Course.query.order_by(Course.title)]
    session_form.teacher_id.choices = [(t.id, t.full_name) for t in Teacher.query.order_by(Teacher.full_name)]
    session_form.room_id.choices = [(r.id, r.name) for r in Room.query.order_by(Room.name)]
    session_form.slot.choices = _slot_choices()

    if session_form.submit.data and session_form.validate_on_submit():
        course = Course.query.get_or_404(session_form.course_id.data)
        slot_index = int(session_form.slot.data)
        slot_start, _ = SLOT_DEFINITION[slot_index]
        start_dt = datetime.combine(session_form.date.data, slot_start)
        end_dt = start_dt + timedelta(hours=course.duration_hours)
        session = CourseSession(
            course_id=course.id,
            teacher_id=session_form.teacher_id.data,
            room_id=session_form.room_id.data,
            start=start_dt,
            end=end_dt,
        )
        db.session.add(session)
        db.session.commit()
        flash("Séance planifiée manuellement.", "success")
        return redirect(url_for("main.dashboard"))

    if quick_plan_form.submit.data and quick_plan_form.validate_on_submit():
        try:
            created = plan_sessions(quick_plan_form.start_day.data, quick_plan_form.horizon_days.data)
            if created:
                flash(f"{created} séances générées automatiquement.", "success")
            else:
                flash("Aucune séance à planifier.", "info")
        except PlanningError as exc:
            flash(str(exc), "danger")
        return redirect(url_for("main.dashboard"))

    sessions = CourseSession.query.order_by(CourseSession.start).all()
    return render_template(
        "index.html",
        sessions=sessions,
        quick_plan_form=quick_plan_form,
        session_form=session_form,
    )


@main_bp.route("/enseignant", methods=["GET", "POST"])
def teacher_list():
    form = TeacherForm()
    if form.validate_on_submit():
        teacher = Teacher(
            full_name=form.full_name.data,
            email=form.email.data,
            max_hours_per_week=form.max_hours_per_week.data,
        )
        db.session.add(teacher)
        db.session.commit()
        flash("Enseignant créé avec succès", "success")
        return redirect(url_for("main.teacher_list"))

    teachers = Teacher.query.order_by(Teacher.full_name).all()
    return render_template("enseignant/list.html", teachers=teachers, form=form)


@main_bp.route("/enseignant/<int:teacher_id>", methods=["GET", "POST"])
def teacher_detail(teacher_id: int):
    teacher = Teacher.query.get_or_404(teacher_id)
    form = TeacherForm(obj=teacher)
    availability_form = TeacherAvailabilityForm()
    unavailability_form = TeacherUnavailabilityForm()

    if form.submit.data and form.validate_on_submit():
        form.populate_obj(teacher)
        db.session.commit()
        flash("Profil enseignant mis à jour", "success")
        return redirect(url_for("main.teacher_detail", teacher_id=teacher.id))

    if availability_form.submit.data and availability_form.validate_on_submit():
        availability = TeacherAvailability(
            weekday=availability_form.weekday.data,
            start_time=availability_form.start_time.data,
            end_time=availability_form.end_time.data,
        )
        teacher.availabilities.append(availability)
        db.session.commit()
        flash("Disponibilité ajoutée", "success")
        return redirect(url_for("main.teacher_detail", teacher_id=teacher.id))

    if unavailability_form.submit.data and unavailability_form.validate_on_submit():
        unavailability = TeacherUnavailability(
            date=unavailability_form.date.data,
            reason=unavailability_form.reason.data or "",
        )
        teacher.unavailabilities.append(unavailability)
        db.session.commit()
        flash("Indisponibilité ajoutée", "success")
        return redirect(url_for("main.teacher_detail", teacher_id=teacher.id))

    sessions = CourseSession.query.filter_by(teacher_id=teacher.id).order_by(CourseSession.start).all()
    return render_template(
        "enseignant/detail.html",
        teacher=teacher,
        form=form,
        availability_form=availability_form,
        unavailability_form=unavailability_form,
        sessions=sessions,
    )


@main_bp.route("/salle", methods=["GET", "POST"])
def room_list():
    form = RoomForm()
    form.materials.choices = [(m.id, m.name) for m in Material.query.order_by(Material.name)]

    if form.validate_on_submit():
        room = Room(
            name=form.name.data,
            capacity=form.capacity.data,
            computers=form.computers.data or 0,
            notes=form.notes.data or "",
        )
        _apply_materials(room, form.materials.data)
        db.session.add(room)
        db.session.commit()
        flash("Salle créée", "success")
        return redirect(url_for("main.room_list"))

    rooms = Room.query.order_by(Room.name).all()
    return render_template("salle/list.html", rooms=rooms, form=form)


@main_bp.route("/salle/<int:room_id>", methods=["GET", "POST"])
def room_detail(room_id: int):
    room = Room.query.get_or_404(room_id)
    form = RoomForm(obj=room)
    form.materials.choices = [(m.id, m.name) for m in Material.query.order_by(Material.name)]
    if not form.is_submitted():
        form.materials.data = [m.id for m in room.materials]

    if form.validate_on_submit():
        form.populate_obj(room)
        _apply_materials(room, form.materials.data)
        db.session.commit()
        flash("Salle mise à jour", "success")
        return redirect(url_for("main.room_detail", room_id=room.id))

    sessions = CourseSession.query.filter_by(room_id=room.id).order_by(CourseSession.start).all()
    return render_template("salle/detail.html", room=room, form=form, sessions=sessions)


@main_bp.route("/matiere", methods=["GET", "POST"])
def course_list():
    form = CourseForm()
    form.materials.choices = [(m.id, m.name) for m in Material.query.order_by(Material.name)]
    form.softwares.choices = [(s.id, s.name) for s in Software.query.order_by(Software.name)]

    if form.validate_on_submit():
        course = Course(
            title=form.title.data,
            duration_hours=form.duration_hours.data,
            session_count=form.session_count.data,
            priority=form.priority.data,
            required_capacity=form.required_capacity.data,
            requires_computers=form.requires_computers.data,
        )
        _apply_materials(course, form.materials.data)
        _apply_softwares(course, form.softwares.data)
        db.session.add(course)
        db.session.commit()
        flash("Cours créé", "success")
        return redirect(url_for("main.course_list"))

    courses = Course.query.order_by(Course.title).all()
    return render_template("matiere/list.html", courses=courses, form=form)


@main_bp.route("/matiere/<int:course_id>", methods=["GET", "POST"])
def course_detail(course_id: int):
    course = Course.query.get_or_404(course_id)
    form = CourseForm(obj=course)
    form.materials.choices = [(m.id, m.name) for m in Material.query.order_by(Material.name)]
    form.softwares.choices = [(s.id, s.name) for s in Software.query.order_by(Software.name)]
    if not form.is_submitted():
        form.materials.data = [m.id for m in course.materials]
        form.softwares.data = [s.id for s in course.softwares]

    if form.validate_on_submit():
        form.populate_obj(course)
        _apply_materials(course, form.materials.data)
        _apply_softwares(course, form.softwares.data)
        db.session.commit()
        flash("Cours mis à jour", "success")
        return redirect(url_for("main.course_detail", course_id=course.id))

    sessions = CourseSession.query.filter_by(course_id=course.id).order_by(CourseSession.start).all()
    return render_template("matiere/detail.html", course=course, form=form, sessions=sessions)


@main_bp.route("/materiel", methods=["GET", "POST"])
def material_list():
    form = MaterialForm()
    if form.validate_on_submit():
        material = Material(name=form.name.data, description=form.description.data or "")
        db.session.add(material)
        db.session.commit()
        flash("Matériel ajouté", "success")
        return redirect(url_for("main.material_list"))

    materials = Material.query.order_by(Material.name).all()
    return render_template("materiel.html", form=form, materials=materials)


@main_bp.route("/logiciel", methods=["GET", "POST"])
def software_list():
    form = SoftwareForm()
    if form.validate_on_submit():
        software = Software(name=form.name.data, version=form.version.data or "latest")
        db.session.add(software)
        db.session.commit()
        flash("Logiciel ajouté", "success")
        return redirect(url_for("main.software_list"))

    softwares = Software.query.order_by(Software.name).all()
    return render_template("logiciel.html", form=form, softwares=softwares)


@main_bp.route("/api/sessions")
def api_sessions():
    sessions = CourseSession.query.all()
    return jsonify([_serialize_session(session) for session in sessions])


@main_bp.route("/api/enseignant/<int:teacher_id>/sessions")
def api_teacher_sessions(teacher_id: int):
    sessions = CourseSession.query.filter_by(teacher_id=teacher_id).all()
    return jsonify([_serialize_session(session) for session in sessions])


@main_bp.route("/api/salle/<int:room_id>/sessions")
def api_room_sessions(room_id: int):
    sessions = CourseSession.query.filter_by(room_id=room_id).all()
    return jsonify([_serialize_session(session) for session in sessions])


@main_bp.route("/api/matiere/<int:course_id>/sessions")
def api_course_sessions(course_id: int):
    sessions = CourseSession.query.filter_by(course_id=course_id).all()
    return jsonify([_serialize_session(session) for session in sessions])
