from __future__ import annotations

import json
from datetime import datetime, time, timedelta, timezone
from typing import Iterable, MutableSequence

from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from . import db
from .events import sessions_to_grouped_events
from .models import (
    COURSE_TYPE_CHOICES,
    ClassGroup,
    ClosingPeriod,
    Course,
    CourseClassLink,
    CourseScheduleLog,
    Equipment,
    Room,
    Session,
    Software,
    Teacher,
    TeacherAvailability,
)
from .scheduler import (
    SCHEDULE_SLOTS,
    START_TIMES,
    fits_in_windows,
    generate_schedule,
    overlaps,
)
from .utils import (
    parse_unavailability_ranges,
    ranges_as_payload,
    serialise_unavailability_ranges,
)

bp = Blueprint("main", __name__)


WORKDAY_START = time(hour=7)
WORKDAY_END = time(hour=19)
BACKGROUND_BLOCK_COLOR = "#6c757d"
CLOSING_PERIOD_COLOR = "rgba(108, 117, 125, 0.45)"

SCHEDULE_SLOT_LOOKUP = {start: end for start, end in SCHEDULE_SLOTS}
SCHEDULE_SLOT_CHOICES = [
    {"start": start.strftime("%H:%M"), "end": end.strftime("%H:%M")}
    for start, end in SCHEDULE_SLOTS
]

COURSE_TYPE_LABELS = {
    "CM": "Cours magistral",
    "TD": "Travaux dirigés",
    "TP": "Travaux pratiques",
    "SAE": "Situation d'apprentissage et d'évaluation",
}


def _normalise_course_type(raw_value: str | None) -> str:
    if not raw_value:
        return "CM"
    raw_value = raw_value.strip().upper()
    if raw_value in COURSE_TYPE_CHOICES:
        return raw_value
    return "CM"


def _build_default_backgrounds() -> list[dict[str, object]]:
    spans: list[tuple[time, time]] = []
    pointer = WORKDAY_START
    for slot_start, slot_end in SCHEDULE_SLOTS:
        slot_start = max(slot_start, WORKDAY_START)
        slot_end = min(slot_end, WORKDAY_END)
        if slot_start > pointer:
            spans.append((pointer, slot_start))
        if slot_end > pointer:
            pointer = slot_end
    if pointer < WORKDAY_END:
        spans.append((pointer, WORKDAY_END))

    backgrounds: list[dict[str, object]] = []
    for span_start, span_end in spans:
        backgrounds.append(
            {
                "daysOfWeek": [1, 2, 3, 4, 5],
                "startTime": span_start.strftime("%H:%M:%S"),
                "endTime": span_end.strftime("%H:%M:%S"),
                "display": "background",
                "overlap": False,
                "color": BACKGROUND_BLOCK_COLOR,
            }
        )
    return backgrounds


DEFAULT_WORKDAY_BACKGROUNDS = _build_default_backgrounds()


def _closing_period_backgrounds() -> list[dict[str, object]]:
    backgrounds: list[dict[str, object]] = []
    periods = ClosingPeriod.ordered_periods()
    for period in periods:
        backgrounds.append(
            {
                "start": period.start_date.strftime("%Y-%m-%dT00:00:00"),
                "end": (period.end_date + timedelta(days=1)).strftime("%Y-%m-%dT00:00:00"),
                "display": "background",
                "overlap": False,
                "color": CLOSING_PERIOD_COLOR,
            }
        )
    return backgrounds


def _unique_entities(entities: Iterable[object]) -> list[object]:
    seen_ids: set[int] = set()
    unique: list[object] = []
    for entity in entities:
        if entity is None:
            continue
        entity_id = getattr(entity, "id", None)
        if entity_id is None:
            unique.append(entity)
            continue
        if entity_id in seen_ids:
            continue
        seen_ids.add(entity_id)
        unique.append(entity)
    return unique


def _sync_simple_relationship(collection: MutableSequence, desired: Iterable[object]) -> None:
    """Synchronise une relation many-to-many en flushant chaque changement."""

    desired_entities = _unique_entities(desired)
    desired_ids = {
        getattr(entity, "id")
        for entity in desired_entities
        if getattr(entity, "id", None) is not None
    }

    for current in list(collection):
        current_id = getattr(current, "id", None)
        if current_id is not None and current_id not in desired_ids:
            collection.remove(current)
            db.session.flush()

    existing_ids = {
        getattr(entity, "id")
        for entity in collection
        if getattr(entity, "id", None) is not None
    }

    for entity in desired_entities:
        entity_id = getattr(entity, "id", None)
        if entity_id is not None and entity_id in existing_ids:
            continue
        collection.append(entity)
        db.session.flush()
        if entity_id is not None:
            existing_ids.add(entity_id)


def _sync_course_class_links(
    course: Course,
    class_ids: Iterable[int],
    *,
    existing_links: dict[int, CourseClassLink] | None = None,
) -> None:
    """Met à jour les associations classes ↔ cours sans insertion en lot."""

    desired_ids = {int(cid) for cid in class_ids}
    current_links = {link.class_group_id: link for link in list(course.class_links)}

    for link in list(course.class_links):
        if link.class_group_id not in desired_ids:
            course.class_links.remove(link)
            db.session.flush()
            current_links.pop(link.class_group_id, None)

    existing_links = existing_links or {}

    for class_id in desired_ids:
        class_group = ClassGroup.query.get(class_id)
        if class_group is None:
            continue
        group_count = 2 if course.is_tp else 1
        link = current_links.get(class_id)
        if link is None:
            preserved = existing_links.get(class_id)
            preserved_teacher_a = preserved.teacher_a if preserved else None
            preserved_teacher_b = preserved.teacher_b if preserved else None
            if course.is_tp:
                base_teacher = preserved_teacher_a or preserved_teacher_b
                teacher_b = base_teacher if base_teacher else None
            elif course.is_sae:
                base_teacher = preserved_teacher_a
                teacher_b = preserved_teacher_b
            else:
                base_teacher = preserved_teacher_a or preserved_teacher_b
                teacher_b = None
            link = CourseClassLink(
                class_group=class_group,
                group_count=group_count,
                teacher_a=base_teacher,
                teacher_b=teacher_b,
            )
            course.class_links.append(link)
            db.session.flush([link])
            current_links[class_id] = link
            continue

        link.group_count = group_count
        if course.is_tp:
            base_teacher = link.teacher_a or link.teacher_b
            if base_teacher and link.teacher_b is None:
                link.teacher_b = base_teacher
        elif course.is_sae:
            # Deux enseignants peuvent être définis, aucune action supplémentaire.
            pass
        else:
            link.teacher_b = None
        db.session.flush([link])


def _parse_unavailability_tokens(raw: str | None) -> set[str]:
    if not raw:
        return set()
    tokens = raw.replace("\n", ",").split(",")
    return {token.strip() for token in tokens if token.strip()}


@bp.app_context_processor
def inject_calendar_defaults() -> dict[str, object]:
    slot_starts = [start.strftime("%H:%M:%S") for start, _ in SCHEDULE_SLOTS]
    return {
        "default_backgrounds_json": json.dumps(DEFAULT_WORKDAY_BACKGROUNDS),
        "background_block_color": BACKGROUND_BLOCK_COLOR,
        "closing_backgrounds_json": json.dumps(_closing_period_backgrounds()),
        "schedule_slot_starts_json": json.dumps(slot_starts),
    }


def _parse_date(value: str | None) -> datetime.date | None:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def _parse_datetime(date_str: str, time_str: str) -> datetime:
    return datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")


def _format_time(value: time) -> str:
    return value.strftime("%H:%M:%S")


def _parse_time_only(value: str | None) -> time | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%H:%M").time()
    except ValueError:
        return None


def _teacher_unavailability_backgrounds(teacher: Teacher) -> list[dict[str, object]]:
    backgrounds: list[dict[str, object]] = []
    for weekday in range(5):
        day_slots = sorted(
            (slot for slot in teacher.availabilities if slot.weekday == weekday),
            key=lambda slot: slot.start_time,
        )
        pointer = WORKDAY_START
        if not day_slots:
            backgrounds.append(
                {
                    "daysOfWeek": [weekday + 1],
                    "startTime": _format_time(WORKDAY_START),
                    "endTime": _format_time(WORKDAY_END),
                    "display": "background",
                    "overlap": False,
                    "color": BACKGROUND_BLOCK_COLOR,
                }
            )
            continue
        for slot in day_slots:
            slot_start = max(slot.start_time, WORKDAY_START)
            slot_end = min(slot.end_time, WORKDAY_END)
            if slot_end <= WORKDAY_START or slot_start >= WORKDAY_END:
                continue
            if slot_start > pointer:
                backgrounds.append(
                    {
                        "daysOfWeek": [weekday + 1],
                        "startTime": _format_time(pointer),
                        "endTime": _format_time(slot_start),
                        "display": "background",
                        "overlap": False,
                        "color": BACKGROUND_BLOCK_COLOR,
                    }
                )
            if slot_end > pointer:
                pointer = slot_end
        if pointer < WORKDAY_END:
            backgrounds.append(
                {
                    "daysOfWeek": [weekday + 1],
                    "startTime": _format_time(pointer),
                    "endTime": _format_time(WORKDAY_END),
                    "display": "background",
                    "overlap": False,
                    "color": BACKGROUND_BLOCK_COLOR,
                }
            )

    for start_day, end_day in parse_unavailability_ranges(teacher.unavailable_dates):
        backgrounds.append(
            {
                "start": start_day.strftime("%Y-%m-%dT00:00:00"),
                "end": (end_day + timedelta(days=1)).strftime("%Y-%m-%dT00:00:00"),
                "display": "background",
                "overlap": False,
                "color": BACKGROUND_BLOCK_COLOR,
            }
        )

    return backgrounds


def _class_unavailability_backgrounds(class_group: ClassGroup) -> list[dict[str, object]]:
    backgrounds: list[dict[str, object]] = []
    for token in _parse_unavailability_tokens(class_group.unavailable_dates):
        try:
            day = datetime.strptime(token, "%Y-%m-%d").date()
        except ValueError:
            continue
        backgrounds.append(
            {
                "start": day.strftime("%Y-%m-%dT00:00:00"),
                "end": (day + timedelta(days=1)).strftime("%Y-%m-%dT00:00:00"),
                "display": "background",
                "overlap": False,
                "color": BACKGROUND_BLOCK_COLOR,
            }
        )
    return backgrounds


def _parse_teacher_selection(raw_value: str | None) -> Teacher | None:
    if not raw_value:
        return None
    try:
        teacher_id = int(raw_value)
    except (TypeError, ValueError):
        return None
    return Teacher.query.get(teacher_id)


def _parse_class_group_choice(raw_value: str | None) -> tuple[int, str | None] | None:
    if not raw_value:
        return None
    class_part, _, label_part = raw_value.partition(":")
    try:
        class_id = int(class_part)
    except ValueError:
        return None
    label = label_part.strip().upper() if label_part else ""
    return class_id, (label or None)


def _has_conflict(
    sessions: list[Session],
    start: datetime,
    end: datetime,
    *,
    ignore_session_id: int | None = None,
) -> bool:
    for session in sessions:
        if ignore_session_id and session.id == ignore_session_id:
            continue
        if overlaps(session.start_time, session.end_time, start, end):
            return True
    return False


def _validate_session_constraints(
    course: Course,
    teacher: Teacher,
    room: Room,
    class_groups: list[ClassGroup],
    start_dt: datetime,
    end_dt: datetime,
    *,
    ignore_session_id: int | None = None,
) -> str | None:
    if start_dt.weekday() >= 5:
        return "Les séances doivent être planifiées du lundi au vendredi."
    if ClosingPeriod.overlaps(start_dt.date(), end_dt.date()):
        return "L'établissement est fermé sur la période sélectionnée."
    if not fits_in_windows(start_dt.time(), end_dt.time()):
        return "Le créneau choisi dépasse les fenêtres horaires autorisées."
    if not teacher.is_available_during(start_dt, end_dt):
        return "L'enseignant n'est pas disponible sur ce créneau."
    if _has_conflict(teacher.sessions, start_dt, end_dt, ignore_session_id=ignore_session_id):
        return "L'enseignant a déjà une séance sur ce créneau."
    if _has_conflict(room.sessions, start_dt, end_dt, ignore_session_id=ignore_session_id):
        return "La salle est déjà réservée sur ce créneau."
    for class_group in class_groups:
        if not class_group.is_available_during(
            start_dt, end_dt, ignore_session_id=ignore_session_id
        ):
            return "La classe est indisponible sur ce créneau."
    required_capacity = sum(course.capacity_needed_for(group) for group in class_groups)
    if room.capacity < required_capacity:
        return (
            "La salle ne peut pas accueillir la taille cumulée des classes "
            f"({required_capacity} étudiants)."
        )
    if course.requires_computers and room.computers <= 0:
        return "La salle ne dispose pas d'ordinateurs alors que le cours en requiert."
    if any(eq not in room.equipments for eq in course.equipments):
        return "La salle ne possède pas l'équipement requis pour ce cours."
    return None


@bp.route("/", methods=["GET", "POST"])
def dashboard():
    courses = (
        Course.query.options(selectinload(Course.generation_logs))
        .order_by(Course.priority.desc())
        .all()
    )
    teachers = Teacher.query.order_by(Teacher.name).all()
    rooms = Room.query.order_by(Room.name).all()
    class_groups = ClassGroup.query.order_by(ClassGroup.name).all()
    equipments = Equipment.query.order_by(Equipment.name).all()
    softwares = Software.query.order_by(Software.name).all()

    course_class_options: dict[int, list[dict[str, str]]] = {}
    course_subgroup_hints: dict[int, bool] = {}
    course_types: dict[int, str] = {}
    global_search_index: list[dict[str, str]] = []
    for course in courses:
        options: list[dict[str, str]] = []
        links = sorted(course.class_links, key=lambda link: link.class_group.name.lower())
        has_subgroups = False
        course_types[course.id] = course.course_type
        if course.is_cm:
            class_names = ", ".join(link.class_group.name for link in links)
            teacher = next((link.teacher_a or link.teacher_b for link in links if link.teacher_a or link.teacher_b), None)
            if teacher is None and course.teachers:
                teacher = course.teachers[0]
            if teacher:
                option_label = f"Toutes les classes ({teacher.name})"
            else:
                option_label = "Toutes les classes (Aucun enseignant)"
            if class_names:
                option_label = f"{option_label} — {class_names}"
            options.append({"value": "ALL", "label": option_label})
        else:
            for link in links:
                for subgroup_label in link.group_labels():
                    value_suffix = subgroup_label or ""
                    option_value = f"{link.class_group_id}:{value_suffix}"
                    base_label = (
                        f"{link.class_group.name} — groupe {subgroup_label.upper()}"
                        if subgroup_label
                        else f"{link.class_group.name} — classe entière"
                    )
                    if course.is_sae:
                        assigned = link.assigned_teachers()
                        if assigned:
                            teacher_names = " & ".join(teacher.name for teacher in assigned)
                            option_label = f"{base_label} ({teacher_names})"
                        else:
                            option_label = f"{base_label} (Aucun enseignant)"
                    else:
                        teacher = link.teacher_for_label(subgroup_label)
                        if teacher:
                            option_label = f"{base_label} ({teacher.name})"
                        else:
                            option_label = f"{base_label} (Aucun enseignant)"
                    options.append({"value": option_value, "label": option_label})
                    if subgroup_label:
                        has_subgroups = True
        course_class_options[course.id] = options
        course_subgroup_hints[course.id] = has_subgroups
        global_search_index.append(
            {
                "label": course.name,
                "type": "Cours",
                "type_label": "Cours",
                "url": url_for("main.course_detail", course_id=course.id),
                "tokens": f"{course.name.lower()} cours",
            }
        )

    for teacher in teachers:
        global_search_index.append(
            {
                "label": teacher.name,
                "type": "Enseignant",
                "type_label": "Enseignant",
                "url": url_for("main.teacher_detail", teacher_id=teacher.id),
                "tokens": f"{teacher.name.lower()} enseignant",
            }
        )

    for room in rooms:
        global_search_index.append(
            {
                "label": room.name,
                "type": "Salle",
                "type_label": "Salle",
                "url": url_for("main.room_detail", room_id=room.id),
                "tokens": f"{room.name.lower()} salle",
            }
        )

    for class_group in class_groups:
        global_search_index.append(
            {
                "label": class_group.name,
                "type": "Classe",
                "type_label": "Classe",
                "url": url_for("main.class_detail", class_id=class_group.id),
                "tokens": f"{class_group.name.lower()} classe",
            }
        )

    for equipment in equipments:
        global_search_index.append(
            {
                "label": equipment.name,
                "type": "Équipement",
                "type_label": "Équipement",
                "url": url_for("main.equipment_list"),
                "tokens": f"{equipment.name.lower()} equipement",
            }
        )

    for software in softwares:
        global_search_index.append(
            {
                "label": software.name,
                "type": "Logiciel",
                "type_label": "Logiciel",
                "url": url_for("main.software_list"),
                "tokens": f"{software.name.lower()} logiciel",
            }
        )

    if request.method == "POST":
        if request.form.get("form") == "quick-session":
            course_id = int(request.form["course_id"])
            teacher_id = int(request.form["teacher_id"])
            room_id = int(request.form["room_id"])
            course = Course.query.get_or_404(course_id)
            teacher = Teacher.query.get_or_404(teacher_id)
            room = Room.query.get_or_404(room_id)
            date_str = request.form["date"]
            start_time_str = request.form["start_time"]
            duration_raw = request.form.get("duration")
            duration = int(duration_raw) if duration_raw else course.session_length_hours
            start_dt = _parse_datetime(date_str, start_time_str)
            end_dt = start_dt + timedelta(hours=duration)
            class_choice_raw = request.form.get("class_group_choice")

            if course.is_cm:
                if not class_choice_raw:
                    flash("Sélectionnez les classes pour la séance", "danger")
                    return redirect(url_for("main.dashboard"))
                class_groups = [link.class_group for link in course.class_links]
                if not class_groups:
                    flash("Associez des classes au cours avant de planifier", "danger")
                    return redirect(url_for("main.dashboard"))
                primary_class = class_groups[0]
                subgroup_label: str | None = None
            else:
                class_choice = _parse_class_group_choice(class_choice_raw)
                if class_choice is None:
                    flash("Sélectionnez une classe pour la séance", "danger")
                    return redirect(url_for("main.dashboard"))
                class_group_id, subgroup_label = class_choice
                class_group = ClassGroup.query.get_or_404(class_group_id)
                if class_group not in course.classes:
                    flash("Associez la classe au cours avant de planifier", "danger")
                    return redirect(url_for("main.dashboard"))
                link = course.class_link_for(class_group)
                if link is None:
                    flash("Associez la classe au cours avant de planifier", "danger")
                    return redirect(url_for("main.dashboard"))
                valid_labels = {label or None for label in link.group_labels()}
                if subgroup_label not in valid_labels:
                    flash("Choisissez un groupe A ou B correspondant à la configuration", "danger")
                    return redirect(url_for("main.dashboard"))
                class_groups = [class_group]
                primary_class = class_group

            error_message = _validate_session_constraints(
                course, teacher, room, class_groups, start_dt, end_dt
            )
            if error_message:
                flash(error_message, "danger")
                return redirect(url_for("main.dashboard"))

            session = Session(
                course_id=course_id,
                teacher_id=teacher_id,
                room_id=room_id,
                class_group_id=primary_class.id,
                subgroup_label=subgroup_label,
                start_time=start_dt,
                end_time=end_dt,
            )
            session.attendees = list(class_groups)
            db.session.add(session)
            db.session.commit()
            flash("Séance créée", "success")
            return redirect(url_for("main.dashboard"))
        elif request.form.get("form") == "bulk-auto-schedule":
            window_start = _parse_date(request.form.get("period_start"))
            window_end = _parse_date(request.form.get("period_end"))
            if not window_start or not window_end:
                flash("Indiquez une période valide pour la génération automatique.", "danger")
                return redirect(url_for("main.dashboard"))
            if window_start > window_end:
                flash("La date de début doit précéder la date de fin.", "danger")
                return redirect(url_for("main.dashboard"))

            total_created = 0
            error_messages: list[str] = []
            for course in courses:
                try:
                    created = generate_schedule(
                        course,
                        window_start=window_start,
                        window_end=window_end,
                    )
                except ValueError as exc:
                    error_messages.append(f"{course.name} : {exc}")
                    continue
                total_created += len(created)

            if total_created:
                db.session.commit()
                flash(f"{total_created} séance(s) générée(s).", "success")
            else:
                db.session.commit()
                flash("Aucune séance n'a pu être générée sur la période indiquée.", "info")

            if error_messages:
                flash("\n".join(error_messages), "warning")

            return redirect(url_for("main.dashboard"))
        elif request.form.get("form") == "clear-course-sessions":
            try:
                course_id = int(request.form.get("course_id", "0"))
            except ValueError:
                flash("Cours invalide", "danger")
                return redirect(url_for("main.dashboard"))

            course = Course.query.get(course_id)
            if course is None:
                flash("Cours introuvable", "danger")
                return redirect(url_for("main.dashboard"))

            removed = len(course.sessions)
            for session in list(course.sessions):
                db.session.delete(session)

            db.session.commit()
            if removed:
                flash(
                    f"{removed} séance(s) supprimée(s) pour {course.name}.",
                    "success",
                )
            else:
                flash("Aucune séance n'était planifiée pour ce cours.", "info")
            return redirect(url_for("main.dashboard"))

    events = sessions_to_grouped_events(Session.query.all())
    course_summaries: list[dict[str, object]] = []
    for course in courses:
        required_total = course.total_required_hours
        scheduled_total = course.scheduled_hours
        remaining = max(required_total - scheduled_total, 0)
        latest_log = course.latest_generation_log
        course_summaries.append(
            {
                "course": course,
                "type_label": COURSE_TYPE_LABELS.get(course.course_type, course.course_type),
                "required": required_total,
                "scheduled": scheduled_total,
                "remaining": remaining,
                "priority": course.priority,
                "latest_status": latest_log.status if latest_log else "none",
                "latest_summary": latest_log.summary if latest_log and latest_log.summary else None,
                "latest_timestamp": latest_log.created_at if latest_log else None,
            }
        )

    return render_template(
        "dashboard.html",
        courses=courses,
        teachers=teachers,
        rooms=rooms,
        class_groups=class_groups,
        course_class_options=course_class_options,
        course_class_options_json=json.dumps(course_class_options, ensure_ascii=False),
        course_subgroup_hints=course_subgroup_hints,
        course_types_json=json.dumps(course_types, ensure_ascii=False),
        course_summaries=course_summaries,
        events_json=json.dumps(events, ensure_ascii=False),
        start_times=START_TIMES,
        course_type_labels=COURSE_TYPE_LABELS,
        global_search_index_json=json.dumps(global_search_index, ensure_ascii=False),
        status_labels=CourseScheduleLog.STATUS_LABELS,
    )


@bp.route("/config", methods=["GET", "POST"])
def configuration():
    if request.method == "POST":
        if request.form.get("form") == "closing-periods":
            ranges = parse_unavailability_ranges(request.form.get("closing_periods"))
            ClosingPeriod.query.delete()
            for start, end in ranges:
                db.session.add(ClosingPeriod(start_date=start, end_date=end))
            db.session.commit()
            flash("Périodes de fermeture mises à jour", "success")
        return redirect(url_for("main.configuration"))

    periods = ClosingPeriod.ordered_periods()
    closing_ranges = ranges_as_payload(period.as_range() for period in periods)

    return render_template(
        "config/index.html",
        closing_periods=closing_ranges,
        closing_period_records=periods,
    )


@bp.route("/enseignant", methods=["GET", "POST"])
def teachers_list():
    if request.method == "POST":
        action = request.form.get("form")
        if action == "create":
            unavailability_value = serialise_unavailability_ranges(
                parse_unavailability_ranges(
                    request.form.get("unavailability_ranges")
                    or request.form.get("unavailable_dates")
                )
            )
            teacher = Teacher(
                name=request.form["name"],
                email=request.form.get("email"),
                phone=request.form.get("phone"),
                unavailable_dates=unavailability_value,
                notes=request.form.get("notes"),
            )
            db.session.add(teacher)
            try:
                db.session.commit()
                flash("Enseignant ajouté", "success")
            except IntegrityError:
                db.session.rollback()
                flash("Nom d'enseignant déjà utilisé", "danger")
        return redirect(url_for("main.teachers_list"))

    teachers = Teacher.query.order_by(Teacher.name).all()
    return render_template("teachers/list.html", teachers=teachers)


@bp.route("/enseignant/<int:teacher_id>", methods=["GET", "POST"])
def teacher_detail(teacher_id: int):
    teacher = Teacher.query.get_or_404(teacher_id)
    courses = Course.query.order_by(Course.name).all()
    assignable_courses = [course for course in courses if teacher not in course.teachers]

    if request.method == "POST":
        form_name = request.form.get("form")
        if form_name == "update":
            new_name = request.form.get("name", "").strip()
            if new_name:
                teacher.name = new_name
            teacher.email = request.form.get("email")
            teacher.phone = request.form.get("phone")
            teacher.unavailable_dates = serialise_unavailability_ranges(
                parse_unavailability_ranges(
                    request.form.get("unavailability_ranges")
                    or request.form.get("unavailable_dates")
                )
            )
            teacher.notes = request.form.get("notes")
            try:
                db.session.commit()
                flash("Fiche enseignant mise à jour", "success")
            except IntegrityError:
                db.session.rollback()
                db.session.refresh(teacher)
                flash("Nom d'enseignant déjà utilisé", "danger")
        elif form_name == "assign-course":
            course_id = int(request.form["course_id"])
            course = Course.query.get_or_404(course_id)
            if teacher not in course.teachers:
                course.teachers.append(teacher)
                db.session.commit()
                flash("Enseignant assigné au cours", "success")
        elif form_name == "set-availability":
            raw_slots = request.form.getlist("availability_slots")
            slots_by_day: dict[int, set[time]] = {weekday: set() for weekday in range(5)}
            for raw in raw_slots:
                try:
                    weekday_str, start_str = raw.split("-", 1)
                    weekday = int(weekday_str)
                except ValueError:
                    continue
                if weekday not in slots_by_day:
                    continue
                slot_start = _parse_time_only(start_str)
                if slot_start is None:
                    continue
                if slot_start not in SCHEDULE_SLOT_LOOKUP:
                    continue
                slots_by_day[weekday].add(slot_start)

            for availability in list(teacher.availabilities):
                db.session.delete(availability)

            for weekday, slot_starts in slots_by_day.items():
                if not slot_starts:
                    continue
                ordered_starts = sorted(slot_starts)
                current_start = ordered_starts[0]
                current_end = SCHEDULE_SLOT_LOOKUP[current_start]
                for next_start in ordered_starts[1:]:
                    next_end = SCHEDULE_SLOT_LOOKUP[next_start]
                    if next_start == current_end:
                        current_end = next_end
                    else:
                        db.session.add(
                            TeacherAvailability(
                                teacher=teacher,
                                weekday=weekday,
                                start_time=current_start,
                                end_time=current_end,
                            )
                        )
                        current_start = next_start
                        current_end = next_end
                db.session.add(
                    TeacherAvailability(
                        teacher=teacher,
                        weekday=weekday,
                        start_time=current_start,
                        end_time=current_end,
                    )
                )
            db.session.commit()
            flash("Disponibilités mises à jour", "success")
        return redirect(url_for("main.teacher_detail", teacher_id=teacher_id))

    events = sessions_to_grouped_events(teacher.sessions)
    selected_slots: set[str] = set()
    for availability in teacher.availabilities:
        if availability.weekday >= 5:
            continue
        for slot_start, slot_end in SCHEDULE_SLOTS:
            if availability.start_time <= slot_start and slot_end <= availability.end_time:
                key = f"{availability.weekday}-{slot_start.strftime('%H:%M')}"
                selected_slots.add(key)

    backgrounds = _teacher_unavailability_backgrounds(teacher)

    return render_template(
        "teachers/detail.html",
        teacher=teacher,
        courses=courses,
        assignable_courses=assignable_courses,
        events_json=json.dumps(events, ensure_ascii=False),
        availability_slots=SCHEDULE_SLOT_CHOICES,
        selected_availability_slots=selected_slots,
        unavailability_backgrounds_json=json.dumps(backgrounds, ensure_ascii=False),
        unavailability_ranges=ranges_as_payload(
            parse_unavailability_ranges(teacher.unavailable_dates)
        ),
    )


@bp.route("/classe", methods=["GET", "POST"])
def classes_list():
    if request.method == "POST":
        action = request.form.get("form")
        if action == "create":
            class_group = ClassGroup(
                name=request.form["name"],
                size=int(request.form.get("size", 20)),
                unavailable_dates=request.form.get("unavailable_dates"),
                notes=request.form.get("notes"),
            )
            db.session.add(class_group)
            try:
                db.session.commit()
                flash("Classe ajoutée", "success")
            except IntegrityError:
                db.session.rollback()
                flash("Nom de classe déjà utilisé", "danger")
        return redirect(url_for("main.classes_list"))

    class_groups = ClassGroup.query.order_by(ClassGroup.name).all()
    return render_template("classes/list.html", class_groups=class_groups)


@bp.route("/classe/<int:class_id>", methods=["GET", "POST"])
def class_detail(class_id: int):
    class_group = ClassGroup.query.get_or_404(class_id)
    courses = Course.query.order_by(Course.name).all()
    assignable_courses = [course for course in courses if class_group not in course.classes]
    teachers = Teacher.query.order_by(Teacher.name).all()

    if request.method == "POST":
        form_name = request.form.get("form")
        if form_name == "update":
            new_name = request.form.get("name", "").strip()
            if new_name:
                class_group.name = new_name
            class_group.size = int(request.form.get("size", class_group.size))
            class_group.unavailable_dates = request.form.get("unavailable_dates")
            class_group.notes = request.form.get("notes")
            try:
                db.session.commit()
                flash("Classe mise à jour", "success")
            except IntegrityError:
                db.session.rollback()
                db.session.refresh(class_group)
                flash("Nom de classe déjà utilisé", "danger")
        elif form_name == "assign-course":
            course_id = int(request.form["course_id"])
            course = Course.query.get_or_404(course_id)
            if class_group not in course.classes:
                group_count = 2 if course.is_tp else 1
                teacher = _parse_teacher_selection(request.form.get("teacher"))
                course.class_links.append(
                    CourseClassLink(
                        class_group=class_group,
                        group_count=group_count,
                        teacher_a=teacher,
                        teacher_b=teacher if group_count == 2 else None,
                    )
                )
                db.session.commit()
                flash("Cours associé à la classe", "success")
        elif form_name == "remove-course":
            course_id = int(request.form["course_id"])
            course = Course.query.get_or_404(course_id)
            link = course.class_link_for(class_group)
            if link is not None:
                course.class_links.remove(link)
                db.session.commit()
                flash("Cours retiré de la classe", "success")
        return redirect(url_for("main.class_detail", class_id=class_id))

    events = sessions_to_grouped_events(class_group.all_sessions)
    unavailability_backgrounds = _class_unavailability_backgrounds(class_group)
    return render_template(
        "classes/detail.html",
        class_group=class_group,
        courses=courses,
        assignable_courses=assignable_courses,
        teachers=teachers,
        events_json=json.dumps(events, ensure_ascii=False),
        unavailability_backgrounds_json=json.dumps(unavailability_backgrounds, ensure_ascii=False),
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
            new_name = request.form.get("name", "").strip()
            if new_name:
                room.name = new_name
            room.capacity = int(request.form.get("capacity", room.capacity))
            room.computers = int(request.form.get("computers", room.computers))
            room.notes = request.form.get("notes")
            try:
                db.session.commit()
                flash("Salle mise à jour", "success")
            except IntegrityError:
                db.session.rollback()
                db.session.refresh(room)
                flash("Nom de salle déjà utilisé", "danger")
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
            new_name = request.form.get("name", "").strip()
            if new_name:
                room.name = new_name
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
            try:
                db.session.commit()
                flash("Salle mise à jour", "success")
            except IntegrityError:
                db.session.rollback()
                db.session.refresh(room)
                flash("Nom de salle déjà utilisé", "danger")
        return redirect(url_for("main.room_detail", room_id=room_id))

    events = sessions_to_grouped_events(room.sessions)
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
    class_groups = ClassGroup.query.order_by(ClassGroup.name).all()
    teachers = Teacher.query.order_by(Teacher.name).all()

    if request.method == "POST":
        form_name = request.form.get("form")
        if form_name == "create":
            course_type = _normalise_course_type(request.form.get("course_type"))
            course = Course(
                name=request.form["name"],
                description=request.form.get("description"),
                session_length_hours=int(request.form.get("session_length_hours", 2)),
                sessions_required=int(request.form.get("sessions_required", 1)),
                start_date=_parse_date(request.form.get("start_date")),
                end_date=_parse_date(request.form.get("end_date")),
                priority=int(request.form.get("priority", 1)),
                course_type=course_type,
                requires_computers=bool(request.form.get("requires_computers")),
            )
            selected_equipments = [
                equipment
                for equipment in (
                    Equipment.query.get(int(eid)) for eid in request.form.getlist("equipments")
                )
                if equipment is not None
            ]
            selected_softwares = [
                software
                for software in (
                    Software.query.get(int(sid)) for sid in request.form.getlist("softwares")
                )
                if software is not None
            ]
            selected_class_ids = {int(cid) for cid in request.form.getlist("classes")}
            db.session.add(course)
            try:
                db.session.flush([course])
                _sync_simple_relationship(course.equipments, selected_equipments)
                _sync_simple_relationship(course.softwares, selected_softwares)
                _sync_course_class_links(course, selected_class_ids)
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
        class_groups=class_groups,
        teachers=teachers,
        course_type_labels=COURSE_TYPE_LABELS,
    )


@bp.route("/matiere/<int:course_id>", methods=["GET", "POST"])
def course_detail(course_id: int):
    course = (
        Course.query.options(selectinload(Course.generation_logs))
        .get_or_404(course_id)
    )
    equipments = Equipment.query.order_by(Equipment.name).all()
    softwares = Software.query.order_by(Software.name).all()
    teachers = Teacher.query.order_by(Teacher.name).all()
    rooms = Room.query.order_by(Room.name).all()
    class_groups = ClassGroup.query.order_by(ClassGroup.name).all()
    class_links_map = {link.class_group_id: link for link in course.class_links}

    if request.method == "POST":
        form_name = request.form.get("form")
        if form_name == "update":
            new_name = request.form.get("name", "").strip()
            if new_name:
                course.name = new_name
            course.description = request.form.get("description")
            course.session_length_hours = int(request.form.get("session_length_hours", course.session_length_hours))
            course.sessions_required = int(request.form.get("sessions_required", course.sessions_required))
            course.start_date = _parse_date(request.form.get("start_date"))
            course.end_date = _parse_date(request.form.get("end_date"))
            course.priority = int(request.form.get("priority", course.priority))
            course.course_type = _normalise_course_type(request.form.get("course_type"))
            course.requires_computers = bool(request.form.get("requires_computers"))
            selected_equipments = [
                equipment
                for equipment in (
                    Equipment.query.get(int(eid)) for eid in request.form.getlist("equipments")
                )
                if equipment is not None
            ]
            selected_softwares = [
                software
                for software in (
                    Software.query.get(int(sid)) for sid in request.form.getlist("softwares")
                )
                if software is not None
            ]
            class_ids = {int(cid) for cid in request.form.getlist("classes")}
            selected_teachers = [
                teacher
                for teacher in (
                    Teacher.query.get(int(tid)) for tid in request.form.getlist("teachers")
                )
                if teacher is not None
            ]

            _sync_simple_relationship(course.equipments, selected_equipments)
            _sync_simple_relationship(course.softwares, selected_softwares)
            _sync_course_class_links(course, class_ids, existing_links=class_links_map)
            _sync_simple_relationship(course.teachers, selected_teachers)
            try:
                db.session.commit()
                flash("Cours mis à jour", "success")
            except IntegrityError:
                db.session.rollback()
                db.session.refresh(course)
                flash("Nom de cours déjà utilisé", "danger")
        elif form_name == "auto-schedule":
            try:
                created_sessions = generate_schedule(course)
                db.session.commit()
                if created_sessions:
                    flash(f"{len(created_sessions)} séance(s) générée(s)", "success")
                else:
                    flash("Aucune séance générée", "info")
            except ValueError as exc:
                db.session.commit()
                flash(str(exc), "danger")
        elif form_name == "update-class-teachers":
            if course.is_cm:
                teacher = _parse_teacher_selection(
                    request.form.get("course_teacher_all")
                )
                for link in course.class_links:
                    link.teacher_a = teacher
                    link.teacher_b = None
            elif course.is_sae:
                for link in course.class_links:
                    teacher_a = _parse_teacher_selection(
                        request.form.get(
                            f"class_link_teacher_a_{link.class_group_id}"
                        )
                    )
                    teacher_b = _parse_teacher_selection(
                        request.form.get(
                            f"class_link_teacher_b_{link.class_group_id}"
                        )
                    )
                    link.teacher_a = teacher_a
                    link.teacher_b = teacher_b
            else:
                for link in course.class_links:
                    teacher = _parse_teacher_selection(
                        request.form.get(f"class_link_teacher_{link.class_group_id}")
                    )
                    link.teacher_a = teacher
                    link.teacher_b = teacher if link.group_count == 2 and teacher else None
            db.session.commit()
            flash("Enseignants par classe mis à jour", "success")
        elif form_name == "manual-session":
            teacher_id = int(request.form["teacher_id"])
            room_id = int(request.form["room_id"])
            class_choice_raw = request.form.get("class_group_choice")
            start_dt = _parse_datetime(request.form["date"], request.form["start_time"])
            duration_raw = request.form.get("duration")
            duration = int(duration_raw) if duration_raw else course.session_length_hours
            end_dt = start_dt + timedelta(hours=duration)
            teacher = Teacher.query.get_or_404(teacher_id)
            room = Room.query.get_or_404(room_id)
            if course.is_cm:
                if not class_choice_raw:
                    flash("Sélectionnez les classes pour la séance", "danger")
                    return redirect(url_for("main.course_detail", course_id=course_id))
                class_groups = [link.class_group for link in course.class_links]
                if not class_groups:
                    flash("Associez d'abord des classes au cours", "danger")
                    return redirect(url_for("main.course_detail", course_id=course_id))
                primary_class = class_groups[0]
                subgroup_label: str | None = None
            else:
                class_choice = _parse_class_group_choice(class_choice_raw)
                if class_choice is None:
                    flash("Sélectionnez un groupe valide pour la classe", "danger")
                    return redirect(url_for("main.course_detail", course_id=course_id))
                class_group_id, subgroup_label = class_choice
                class_group = ClassGroup.query.get_or_404(class_group_id)
                if class_group not in course.classes:
                    flash("Associez d'abord la classe au cours", "danger")
                    return redirect(url_for("main.course_detail", course_id=course_id))
                link = course.class_link_for(class_group)
                if link is None:
                    flash("Associez d'abord la classe au cours", "danger")
                    return redirect(url_for("main.course_detail", course_id=course_id))
                valid_labels = {label or None for label in link.group_labels()}
                if subgroup_label not in valid_labels:
                    flash("Choisissez un groupe A ou B correspondant à la configuration", "danger")
                    return redirect(url_for("main.course_detail", course_id=course_id))
                class_groups = [class_group]
                primary_class = class_group
            error_message = _validate_session_constraints(
                course,
                teacher,
                room,
                class_groups,
                start_dt,
                end_dt,
            )
            if error_message:
                flash(error_message, "danger")
                return redirect(url_for("main.course_detail", course_id=course_id))
            session = Session(
                course_id=course.id,
                teacher_id=teacher_id,
                room_id=room_id,
                class_group_id=primary_class.id,
                subgroup_label=subgroup_label,
                start_time=start_dt,
                end_time=end_dt,
            )
            session.attendees = list(class_groups)
            db.session.add(session)
            db.session.commit()
            flash("Séance ajoutée", "success")
        elif form_name == "clear-sessions":
            removed = len(course.sessions)
            for session in list(course.sessions):
                db.session.delete(session)
            db.session.commit()
            if removed:
                flash("Toutes les séances de ce cours ont été supprimées.", "success")
            else:
                flash("Aucune séance n'était planifiée pour ce cours.", "info")
        return redirect(url_for("main.course_detail", course_id=course_id))

    events = sessions_to_grouped_events(course.sessions)
    generation_logs = (
        CourseScheduleLog.query.filter_by(course_id=course.id)
        .order_by(CourseScheduleLog.created_at.desc())
        .limit(5)
        .all()
    )

    status_badges = {
        "success": "bg-success",
        "warning": "bg-warning text-dark",
        "error": "bg-danger",
        "none": "bg-secondary",
    }
    level_badges = {
        "info": "bg-secondary",
        "warning": "bg-warning text-dark",
        "error": "bg-danger",
    }

    return render_template(
        "courses/detail.html",
        course=course,
        equipments=equipments,
        softwares=softwares,
        teachers=teachers,
        rooms=rooms,
        class_groups=class_groups,
        class_links_map=class_links_map,
        events_json=json.dumps(events, ensure_ascii=False),
        start_times=START_TIMES,
        generation_logs=generation_logs,
        status_labels=CourseScheduleLog.STATUS_LABELS,
        status_badges=status_badges,
        level_badges=level_badges,
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


def _parse_iso_datetime(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


@bp.route("/sessions/<int:session_id>/move", methods=["POST"])
def move_session(session_id: int):
    session = Session.query.get_or_404(session_id)
    payload = request.get_json(silent=True) or {}
    start_raw = payload.get("start")
    end_raw = payload.get("end")
    if not start_raw or not end_raw:
        return {"error": "Données incomplètes"}, 400
    try:
        start_dt = _parse_iso_datetime(start_raw)
        end_dt = _parse_iso_datetime(end_raw)
    except ValueError:
        return {"error": "Format de date invalide"}, 400
    if end_dt <= start_dt:
        return {"error": "L'heure de fin doit être postérieure à l'heure de début"}, 400

    attendee_classes = list(session.attendees) or [session.class_group]
    error_message = _validate_session_constraints(
        session.course,
        session.teacher,
        session.room,
        attendee_classes,
        start_dt,
        end_dt,
        ignore_session_id=session.id,
    )
    if error_message:
        return {"error": error_message}, 400

    session.start_time = start_dt
    session.end_time = end_dt
    db.session.commit()
    return {"event": session.as_event()}


@bp.route("/sessions/<int:session_id>", methods=["DELETE"])
def delete_session(session_id: int):
    session = Session.query.get_or_404(session_id)
    db.session.delete(session)
    db.session.commit()
    return {"status": "deleted"}
