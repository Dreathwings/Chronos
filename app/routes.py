from __future__ import annotations

import json
import math
import threading
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable, List, MutableSequence

from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from sqlalchemy import case, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from . import db
from .events import sessions_to_grouped_events
from .models import (
    COURSE_TYPE_CHOICES,
    COURSE_TYPE_PLACEMENT_ORDER,
    ClassGroup,
    ClosingPeriod,
    Course,
    CourseAllowedWeek,
    CourseClassLink,
    CourseScheduleLog,
    CourseName,
    Equipment,
    Room,
    Session,
    Student,
    Software,
    Teacher,
    TeacherAvailability,
    SEMESTER_CHOICES,
    recommend_teacher_duos_for_classes,
    semester_date_window,
)
from .progress import progress_registry, ScheduleProgressTracker
from .scheduler import (
    SCHEDULE_SLOTS,
    START_TIMES,
    fits_in_windows,
    format_class_label,
    generate_schedule,
    has_weekly_course_conflict,
    overlaps,
    respects_weekly_chronology,
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
CLOSING_PERIOD_COLOR = "#333333"

SCHEDULE_SLOT_LOOKUP = {start: end for start, end in SCHEDULE_SLOTS}
SCHEDULE_SLOT_CHOICES = [
    {"start": start.strftime("%H:%M"), "end": end.strftime("%H:%M")}
    for start, end in SCHEDULE_SLOTS
]

COURSE_TYPE_LABELS = {
    "CM": "CM",
    "TD": "TD",
    "TP": "TP",
    "SAE": "SAE",
    "Eval": "Évaluation",
}
DEFAULT_SEMESTER = SEMESTER_CHOICES[0]

COURSE_TYPE_CANONICAL = {
    choice.upper(): choice for choice in COURSE_TYPE_CHOICES
}

COURSE_TYPE_ORDER_EXPRESSION = case(
    *[
        (func.upper(Course.course_type) == label.upper(), index)
        for index, label in enumerate(COURSE_TYPE_PLACEMENT_ORDER)
    ],
    else_=len(COURSE_TYPE_PLACEMENT_ORDER),
)

GENERATION_STATUS_LABELS = {**CourseScheduleLog.STATUS_LABELS, "none": "Jamais généré"}

STATUS_BADGES = {
    "success": "bg-success",
    "warning": "bg-warning text-dark",
    "error": "bg-danger",
    "none": "bg-secondary",
}

LEVEL_BADGES = {
    "info": "bg-secondary",
    "warning": "bg-warning text-dark",
    "error": "bg-danger",
}

STUDENT_PATHWAY_CHOICES = {
    "initial": "Initial",
    "alternance": "Alternance",
}

STUDENT_GROUP_CHOICES: tuple[str, ...] = ("A", "B")


def _normalise_course_type(raw_value: str | None) -> str:
    if not raw_value:
        return "CM"
    value = raw_value.strip()
    if not value:
        return "CM"
    canonical = COURSE_TYPE_CANONICAL.get(value.upper())
    if canonical:
        return canonical
    return "CM"


def _normalise_semester(raw_value: str | None) -> str:
    if not raw_value:
        return DEFAULT_SEMESTER
    value = raw_value.strip().upper()
    if value in SEMESTER_CHOICES:
        return value
    return DEFAULT_SEMESTER


def _parse_non_negative_int(raw_value: str | None, default: int = 0) -> int:
    if not raw_value:
        return default
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return default
    return max(value, 0)


def _clear_course_schedule(course: Course) -> tuple[int, int]:
    removed_sessions = len(course.sessions)
    for session in list(course.sessions):
        db.session.delete(session)

    removed_logs = len(course.generation_logs)
    for log in list(course.generation_logs):
        db.session.delete(log)

    return removed_sessions, removed_logs


def _build_default_backgrounds() -> list[dict[str, object]]:
    backgrounds: list[dict[str, object]] = []
    if not SCHEDULE_SLOTS:
        backgrounds.append(
            {
                "daysOfWeek": [1, 2, 3, 4, 5],
                "startTime": WORKDAY_START.strftime("%H:%M:%S"),
                "endTime": WORKDAY_END.strftime("%H:%M:%S"),
                "display": "background",
                "overlap": False,
                "color": BACKGROUND_BLOCK_COLOR,
            }
        )
        return backgrounds

    ordered_slots = sorted(SCHEDULE_SLOTS, key=lambda entry: entry[0])
    first_start = max(ordered_slots[0][0], WORKDAY_START)
    last_end = min(ordered_slots[-1][1], WORKDAY_END)

    if first_start > WORKDAY_START:
        backgrounds.append(
            {
                "daysOfWeek": [1, 2, 3, 4, 5],
                "startTime": WORKDAY_START.strftime("%H:%M:%S"),
                "endTime": first_start.strftime("%H:%M:%S"),
                "display": "background",
                "overlap": False,
                "color": BACKGROUND_BLOCK_COLOR,
            }
        )
    if last_end < WORKDAY_END:
        backgrounds.append(
            {
                "daysOfWeek": [1, 2, 3, 4, 5],
                "startTime": last_end.strftime("%H:%M:%S"),
                "endTime": WORKDAY_END.strftime("%H:%M:%S"),
                "display": "background",
                "overlap": False,
                "color": BACKGROUND_BLOCK_COLOR,
            }
        )
    return backgrounds


DEFAULT_WORKDAY_BACKGROUNDS = _build_default_backgrounds()


def _build_pause_backgrounds() -> list[dict[str, object]]:
    backgrounds: list[dict[str, object]] = []
    ordered_slots = sorted(SCHEDULE_SLOTS, key=lambda entry: entry[0])
    pointer: time | None = None
    for raw_start, raw_end in ordered_slots:
        slot_start = max(raw_start, WORKDAY_START)
        slot_end = min(raw_end, WORKDAY_END)
        if slot_end <= WORKDAY_START or slot_start >= WORKDAY_END:
            continue
        if pointer is None:
            pointer = slot_end
            continue
        if slot_start > pointer:
            backgrounds.append(
                {
                    "daysOfWeek": [1, 2, 3, 4, 5],
                    "startTime": pointer.strftime("%H:%M:%S"),
                    "endTime": slot_start.strftime("%H:%M:%S"),
                    "display": "background",
                    "overlap": False,
                    "color": BACKGROUND_BLOCK_COLOR,
                }
            )
        if slot_end > pointer:
            pointer = slot_end
    return backgrounds


PAUSE_BACKGROUNDS = _build_pause_backgrounds()


def _format_hours(value: float) -> str:
    rounded = round(value)
    if abs(value - rounded) < 1e-6:
        return str(int(rounded))
    return f"{value:.1f}".rstrip("0").rstrip(".")


def _effective_generation_status(
    course: Course,
    latest_log: CourseScheduleLog | None,
    *,
    remaining_hours: float | None = None,
) -> str:
    if latest_log is None:
        return "none"
    status = latest_log.status
    if status not in {"warning", "error"}:
        return status

    required_total = float(course.total_required_hours or 0)
    scheduled_total = float(course.scheduled_hours or 0)
    if remaining_hours is None:
        remaining_hours = max(required_total - scheduled_total, 0.0)

    if scheduled_total > 0 and math.isclose(remaining_hours, 0.0, abs_tol=1e-6):
        return "success"
    return status


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


def _closing_period_spans() -> list[tuple[date, date]]:
    periods = ClosingPeriod.ordered_periods()
    spans = [(period.start_date, period.end_date) for period in periods]
    if not spans:
        return []
    spans.sort(key=lambda span: span[0])
    merged: list[tuple[date, date]] = []
    for start, end in spans:
        if not merged:
            merged.append((start, end))
            continue
        previous_start, previous_end = merged[-1]
        if start <= previous_end + timedelta(days=1):
            merged[-1] = (previous_start, max(previous_end, end))
        else:
            merged.append((start, end))
    return merged


def _is_day_within_closing_periods(day: date, spans: list[tuple[date, date]]) -> bool:
    if not spans:
        return False
    for start, end in spans:
        if start > day:
            break
        if start <= day <= end:
            return True
    return False


def _is_week_closed(
    week_start: date, week_end: date, spans: list[tuple[date, date]]
) -> bool:
    if not spans:
        return False
    current = week_start
    while current <= week_end:
        if not _is_day_within_closing_periods(current, spans):
            return False
        current += timedelta(days=1)
    return True


def _week_bounds_for(day: date) -> tuple[date, date]:
    start = day - timedelta(days=day.weekday())
    end = start + timedelta(days=6)
    return start, end


def _semester_week_ranges(semester: str) -> list[tuple[date, date]]:
    window = semester_date_window(semester)
    if window is None:
        return []

    min_start, max_end = window
    start, _ = _week_bounds_for(min_start)
    _, end = _week_bounds_for(max_end)

    ranges: list[tuple[date, date]] = []
    current = start
    closing_spans = _closing_period_spans()
    while current <= end:
        week_end = current + timedelta(days=6)
        if not _is_week_closed(current, week_end, closing_spans):
            ranges.append((current, week_end))
        current += timedelta(days=7)
    return ranges


def _week_label(start: date, end: date) -> str:
    iso_year, iso_week, _ = start.isocalendar()
    return (
        f"S{iso_week:02d} {iso_year} — "
        f"{start.strftime('%d/%m/%Y')} → {end.strftime('%d/%m/%Y')}"
    )


def _parse_week_selection(values: Iterable[str]) -> list[tuple[date, date]]:
    selections: list[tuple[date, date]] = []
    seen: set[date] = set()
    for raw in values:
        week_start = _parse_date(raw)
        if week_start is None:
            continue
        span_start, span_end = _week_bounds_for(week_start)
        if span_start in seen:
            continue
        seen.add(span_start)
        selections.append((span_start, span_end))
    selections.sort(key=lambda span: span[0])
    return selections


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


def _sync_course_allowed_weeks(course: Course, week_starts: Iterable[date]) -> None:
    closing_spans = _closing_period_spans()
    desired: list[date] = []
    seen: set[date] = set()
    for raw_start in week_starts:
        if raw_start is None:
            continue
        week_start, week_end = _week_bounds_for(raw_start)
        if week_start in seen:
            continue
        if _is_week_closed(week_start, week_end, closing_spans):
            continue
        seen.add(week_start)
        desired.append(week_start)
    desired.sort()
    desired_set = set(desired)

    for entry in list(course.allowed_weeks):
        if entry.week_start not in desired_set:
            course.allowed_weeks.remove(entry)
            db.session.flush()

    existing_starts = {entry.week_start for entry in course.allowed_weeks}
    for week_start in desired:
        if week_start in existing_starts:
            continue
        course.allowed_weeks.append(CourseAllowedWeek(week_start=week_start))
        db.session.flush()
        existing_starts.add(week_start)

    occurrence_goal = len(course.allowed_weeks)
    course.sessions_required = max(occurrence_goal, 1)


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
        preserved = existing_links.get(class_id)
        preserved_teacher_a = preserved.teacher_a if preserved else None
        preserved_teacher_b = preserved.teacher_b if preserved else None
        preserved_name_a = preserved.subgroup_a_course_name if preserved else None
        preserved_name_b = preserved.subgroup_b_course_name if preserved else None
        if link is None:
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
                subgroup_a_course_name=preserved_name_a,
                subgroup_b_course_name=preserved_name_b,
            )
            course.class_links.append(link)
            current_links[class_id] = link

        link.group_count = group_count
        if course.is_tp:
            base_teacher = link.teacher_a or link.teacher_b
            if base_teacher and link.teacher_b is None:
                link.teacher_b = base_teacher
            if link.subgroup_a_course_name is None:
                link.subgroup_a_course_name = preserved_name_a
            if link.subgroup_b_course_name is None:
                link.subgroup_b_course_name = preserved_name_b
        elif course.is_sae:
            # Deux enseignants obligatoires sont gérés lors de la mise à jour dédiée.
            pass
        else:
            link.teacher_b = None
            link.subgroup_a_course_name = None
            link.subgroup_b_course_name = None
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
        "pause_backgrounds_json": json.dumps(PAUSE_BACKGROUNDS),
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


def _parse_teacher_selection(
    raw_value: str | None, *, allowed_ids: set[int] | None = None
) -> Teacher | None:
    if not raw_value:
        return None
    try:
        teacher_id = int(raw_value)
    except (TypeError, ValueError):
        return None
    if allowed_ids is not None and teacher_id not in allowed_ids:
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
    class_group_labels: dict[int, str | None] | None = None,
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
        subgroup_label: str | None = None
        if class_group_labels is not None and class_group.id is not None:
            subgroup_label = class_group_labels.get(class_group.id)
        candidate_hours = max(int((end_dt - start_dt).total_seconds() // 3600), 0)
        if not class_group.is_available_during(
            start_dt,
            end_dt,
            ignore_session_id=ignore_session_id,
            subgroup_label=subgroup_label,
        ):
            return "La classe est indisponible sur ce créneau."
        if has_weekly_course_conflict(
            course,
            class_group,
            start_dt,
            subgroup_label=subgroup_label,
            ignore_session_id=ignore_session_id,
            additional_hours=candidate_hours,
        ):
            week_start = start_dt.date() - timedelta(days=start_dt.weekday())
            link = course.class_link_for(class_group)
            label = format_class_label(
                class_group, link=link, subgroup_label=subgroup_label
            )
            return (
                "La durée hebdomadaire autorisée pour "
                f"{label} est déjà atteinte sur la semaine du "
                f"{week_start.strftime('%d/%m/%Y')}"
                "."
            )
        if not respects_weekly_chronology(
            course,
            class_group,
            start_dt,
            subgroup_label=subgroup_label,
            ignore_session_id=ignore_session_id,
        ):
            return (
                "La séance ne respecte pas la chronologie CM → TD → TP → Eval "
                "sur la semaine."
            )
    required_capacity = sum(course.capacity_needed_for(group) for group in class_groups)
    if room.capacity < required_capacity:
        return (
            "La salle ne peut pas accueillir la taille cumulée des classes "
            f"({required_capacity} étudiants)."
        )
    required_posts = course.required_computer_posts()
    if required_posts and (room.computers or 0) < required_posts:
        if required_posts == 1:
            return "La salle ne dispose pas d'ordinateur alors que le cours en requiert."
        return (
            "La salle ne propose pas suffisamment de postes informatiques "
            f"({required_posts} requis)."
        )
    if any(eq not in room.equipments for eq in course.equipments):
        return "La salle ne possède pas l'équipement requis pour ce cours."
    return None


@bp.route("/", methods=["GET", "POST"])
def dashboard():
    courses = (
        Course.query.options(selectinload(Course.generation_logs))
        .order_by(COURSE_TYPE_ORDER_EXPRESSION, Course.name.asc())
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

            class_group_labels: dict[int, str | None] | None = None
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
                class_group_labels = {class_group.id: subgroup_label}

            error_message = _validate_session_constraints(
                course,
                teacher,
                room,
                class_groups,
                start_dt,
                end_dt,
                class_group_labels=class_group_labels,
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
            if _wants_json_response():
                tracker = _enqueue_bulk_schedule()
                response = {
                    "job_id": tracker.job_id,
                    "status_url": url_for(
                        "main.schedule_progress_status", job_id=tracker.job_id
                    ),
                    "redirect_url": url_for("main.dashboard"),
                    "label": "Génération globale",
                }
                return jsonify(response), 202
            total_created = 0
            error_messages: list[str] = []
            for course in courses:
                allowed_ranges = course.allowed_week_ranges
                window_start = allowed_ranges[0][0] if allowed_ranges else None
                window_end = allowed_ranges[-1][1] if allowed_ranges else None
                try:
                    created = generate_schedule(
                        course,
                        window_start=window_start,
                        window_end=window_end,
                        allowed_weeks=allowed_ranges if allowed_ranges else None,
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
                flash(
                    "Aucune séance n'a pu être générée avec les contraintes actuelles.",
                    "info",
                )

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

            removed, _ = _clear_course_schedule(course)
            db.session.commit()
            if removed:
                flash(
                    f"{removed} séance(s) supprimée(s) pour {course.name}.",
                    "success",
                )
            else:
                flash("Aucune séance n'était planifiée pour ce cours.", "info")
            return redirect(url_for("main.dashboard"))
        elif request.form.get("form") == "clear-all-sessions":
            total_removed_sessions = 0
            total_removed_logs = 0
            for course in courses:
                removed_sessions, removed_logs = _clear_course_schedule(course)
                total_removed_sessions += removed_sessions
                total_removed_logs += removed_logs

            db.session.commit()

            if total_removed_sessions or total_removed_logs:
                message_parts: list[str] = []
                if total_removed_sessions:
                    message_parts.append(
                        f"{total_removed_sessions} séance(s) planifiée(s)"
                    )
                if total_removed_logs:
                    message_parts.append(
                        f"{total_removed_logs} journal(aux) de génération"
                    )
                detail = " et ".join(message_parts)
                flash(
                    f"{detail} supprimé(s) pour l'ensemble des cours.",
                    "success",
                )
            else:
                flash(
                    "Aucune séance planifiée ni journal de génération à supprimer.",
                    "info",
                )

            return redirect(url_for("main.dashboard"))

    all_sessions = Session.query.all()
    events = sessions_to_grouped_events(all_sessions)
    has_any_scheduled_sessions = len(all_sessions) > 0
    course_summaries: list[dict[str, object]] = []
    for course in courses:
        required_total = course.total_required_hours
        scheduled_total = course.scheduled_hours
        remaining = max(required_total - scheduled_total, 0)
        latest_log = course.latest_generation_log
        display_status = _effective_generation_status(
            course,
            latest_log,
            remaining_hours=remaining,
        )
        course_summaries.append(
            {
                "course": course,
                "type_label": COURSE_TYPE_LABELS.get(course.course_type, course.course_type),
                "required": required_total,
                "scheduled": scheduled_total,
                "remaining": remaining,
                "latest_status": latest_log.status if latest_log else "none",
                "display_status": display_status,
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
        status_labels=GENERATION_STATUS_LABELS,
        has_any_scheduled_sessions=has_any_scheduled_sessions,
    )


@bp.route("/config", methods=["GET", "POST"])
def configuration():
    course_names = CourseName.query.order_by(CourseName.name).all()
    equipments = Equipment.query.order_by(Equipment.name).all()
    softwares = Software.query.order_by(Software.name).all()
    rooms = Room.query.order_by(Room.name).all()

    if request.method == "POST":
        form_name = request.form.get("form")
        if form_name == "closing-periods":
            ranges = parse_unavailability_ranges(request.form.get("closing_periods"))
            ClosingPeriod.query.delete()
            for start, end in ranges:
                db.session.add(ClosingPeriod(start_date=start, end_date=end))
            db.session.commit()
            flash("Périodes de fermeture mises à jour", "success")
        elif form_name == "course-name-create":
            name = (request.form.get("name") or "").strip()
            if not name:
                flash("Indiquez un nom de cours valide", "danger")
            else:
                db.session.add(CourseName(name=name))
                try:
                    db.session.commit()
                    flash("Nom de cours ajouté", "success")
                except IntegrityError:
                    db.session.rollback()
                    flash("Ce nom de cours existe déjà", "danger")
        elif form_name == "course-name-preferences":
            course_name_id = request.form.get("course_name_id")
            try:
                course_name = CourseName.query.get(int(course_name_id)) if course_name_id else None
            except (TypeError, ValueError):
                course_name = None
            if not course_name:
                flash("Nom de cours introuvable", "danger")
            else:
                selected_ids = {
                    int(room_id)
                    for room_id in request.form.getlist("preferred_rooms")
                    if room_id.isdigit()
                }
                preferred_rooms = [
                    room for room in rooms if room.id in selected_ids
                ]
                course_name.preferred_rooms = preferred_rooms
                db.session.commit()
                flash("Salles privilégiées mises à jour", "success")
        elif form_name == "equipment-create":
            name = (request.form.get("name") or "").strip()
            if not name:
                flash("Indiquez un nom d'équipement", "danger")
            else:
                db.session.add(Equipment(name=name))
                try:
                    db.session.commit()
                    flash("Équipement ajouté", "success")
                except IntegrityError:
                    db.session.rollback()
                    flash("Équipement déjà existant", "danger")
        elif form_name == "software-create":
            name = (request.form.get("name") or "").strip()
            if not name:
                flash("Indiquez un nom de logiciel", "danger")
            else:
                db.session.add(Software(name=name))
                try:
                    db.session.commit()
                    flash("Logiciel ajouté", "success")
                except IntegrityError:
                    db.session.rollback()
                    flash("Logiciel déjà existant", "danger")
        return redirect(url_for("main.configuration"))

    periods = ClosingPeriod.ordered_periods()
    closing_ranges = ranges_as_payload(period.as_range() for period in periods)

    return render_template(
        "config/index.html",
        closing_periods=closing_ranges,
        closing_period_records=periods,
        course_names=course_names,
        equipments=equipments,
        softwares=softwares,
        rooms=rooms,
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
    courses = (
        Course.query.order_by(COURSE_TYPE_ORDER_EXPRESSION, Course.name.asc()).all()
    )
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

    if not selected_slots:
        for weekday in range(5):
            for slot_start, _ in SCHEDULE_SLOTS:
                selected_slots.add(f"{weekday}-{slot_start.strftime('%H:%M')}")

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


@bp.route("/etudiants")
def students_list():
    search_query = (request.args.get("q") or "").strip()
    class_id_raw = request.args.get("class_id")
    group_filter = (request.args.get("group") or "").strip().upper() or None
    phase_filter = request.args.get("phase") or None
    pathway_filter = request.args.get("pathway") or None

    try:
        selected_class_id = int(class_id_raw) if class_id_raw else None
    except (TypeError, ValueError):
        selected_class_id = None

    group_options = list(STUDENT_GROUP_CHOICES)
    if group_filter not in STUDENT_GROUP_CHOICES:
        group_filter = None

    phase_options = [
        value
        for (value,) in db.session.query(Student.phase)
        .filter(Student.phase.isnot(None), Student.phase != "")
        .distinct()
        .order_by(Student.phase.asc())
        .all()
    ]
    if phase_filter not in phase_options:
        phase_filter = None

    if pathway_filter not in STUDENT_PATHWAY_CHOICES:
        pathway_filter = None

    query = Student.query.options(selectinload(Student.class_group))
    if selected_class_id:
        query = query.filter(Student.class_group_id == selected_class_id)
    if group_filter:
        query = query.filter(Student.group_label == group_filter)
    if phase_filter:
        query = query.filter(Student.phase == phase_filter)
    if pathway_filter:
        query = query.filter(Student.pathway == pathway_filter)
    if search_query:
        like_pattern = f"%{search_query}%"
        query = query.filter(
            or_(
                Student.full_name.ilike(like_pattern),
                Student.email.ilike(like_pattern),
                Student.ina_id.ilike(like_pattern),
                Student.ub_id.ilike(like_pattern),
            )
        )

    students = query.order_by(func.lower(Student.full_name)).all()
    class_groups = ClassGroup.query.order_by(ClassGroup.name.asc()).all()
    has_active_filters = bool(
        search_query
        or selected_class_id
        or group_filter
        or phase_filter
        or pathway_filter
    )

    return render_template(
        "students/list.html",
        students=students,
        class_groups=class_groups,
        search_query=search_query,
        selected_class_id=selected_class_id,
        selected_group=group_filter,
        selected_phase=phase_filter,
        selected_pathway=pathway_filter,
        group_options=group_options,
        phase_options=phase_options,
        pathway_choices=STUDENT_PATHWAY_CHOICES,
        has_active_filters=has_active_filters,
    )


@bp.route("/etudiants/nouveau", methods=["GET", "POST"])
def student_create():
    class_groups = ClassGroup.query.order_by(ClassGroup.name.asc()).all()
    phase_options = [
        value
        for (value,) in db.session.query(Student.phase)
        .filter(Student.phase.isnot(None), Student.phase != "")
        .distinct()
        .order_by(Student.phase.asc())
        .all()
    ]

    form_data = {
        "full_name": "",
        "email": "",
        "class_group_id": "",
        "group_label": "",
        "phase": "",
        "pathway": "initial",
        "alternance_details": "",
        "ina_id": "",
        "ub_id": "",
        "notes": "",
    }

    if request.method == "POST":
        for key in form_data:
            form_data[key] = (request.form.get(key) or "")
        full_name = form_data["full_name"].strip()
        if not full_name:
            flash("Renseignez le nom de l'étudiant.", "warning")
        else:
            class_group: ClassGroup | None = None
            class_group_id_raw = form_data.get("class_group_id") or ""
            if class_group_id_raw:
                try:
                    class_group_id = int(class_group_id_raw)
                except ValueError:
                    flash("Classe invalide sélectionnée.", "danger")
                    return render_template(
                        "students/create.html",
                        class_groups=class_groups,
                        group_options=STUDENT_GROUP_CHOICES,
                        phase_options=phase_options,
                        pathway_choices=STUDENT_PATHWAY_CHOICES,
                        form_data=form_data,
                    )
                class_group = db.session.get(ClassGroup, class_group_id)
                if class_group is None:
                    flash("Classe introuvable.", "danger")
                    return render_template(
                        "students/create.html",
                        class_groups=class_groups,
                        group_options=STUDENT_GROUP_CHOICES,
                        phase_options=phase_options,
                        pathway_choices=STUDENT_PATHWAY_CHOICES,
                        form_data=form_data,
                    )

            group_label = form_data["group_label"].strip().upper() or None
            if group_label not in STUDENT_GROUP_CHOICES:
                group_label = None

            pathway = form_data["pathway"] or "initial"
            if pathway not in STUDENT_PATHWAY_CHOICES:
                pathway = "initial"

            alternance_details = form_data["alternance_details"].strip() or None
            if pathway != "alternance":
                alternance_details = None

            student = Student(
                full_name=full_name,
                email=form_data["email"].strip() or None,
                class_group=class_group,
                group_label=group_label,
                phase=form_data["phase"].strip() or None,
                pathway=pathway,
                alternance_details=alternance_details,
                ina_id=form_data["ina_id"].strip() or None,
                ub_id=form_data["ub_id"].strip() or None,
                notes=form_data["notes"].strip() or None,
            )
            db.session.add(student)
            db.session.commit()
            flash("Étudiant créé", "success")
            return redirect(url_for("main.student_detail", student_id=student.id))

    return render_template(
        "students/create.html",
        class_groups=class_groups,
        group_options=STUDENT_GROUP_CHOICES,
        phase_options=phase_options,
        pathway_choices=STUDENT_PATHWAY_CHOICES,
        form_data=form_data,
    )


@bp.route("/etudiants/<int:student_id>", methods=["GET", "POST"])
def student_detail(student_id: int):
    student = (
        Student.query.options(selectinload(Student.class_group))
        .get_or_404(student_id)
    )

    class_groups = ClassGroup.query.order_by(ClassGroup.name.asc()).all()
    phase_options = [
        value
        for (value,) in db.session.query(Student.phase)
        .filter(Student.phase.isnot(None), Student.phase != "")
        .distinct()
        .order_by(Student.phase.asc())
        .all()
    ]
    group_options = list(STUDENT_GROUP_CHOICES)

    if request.method == "POST":
        if request.form.get("form") == "update":
            full_name = (request.form.get("full_name") or "").strip()
            if full_name:
                student.full_name = full_name
            student.email = (request.form.get("email") or "").strip() or None
            group_label = (request.form.get("group_label") or "").strip().upper() or None
            if group_label not in STUDENT_GROUP_CHOICES:
                group_label = None
            student.group_label = group_label
            student.phase = (request.form.get("phase") or "").strip() or None
            pathway = request.form.get("pathway") or student.pathway
            if pathway not in STUDENT_PATHWAY_CHOICES:
                pathway = student.pathway
            student.pathway = pathway
            alternance_details = (
                (request.form.get("alternance_details") or "").strip() or None
            )
            if student.pathway != "alternance":
                alternance_details = None
            student.alternance_details = alternance_details
            student.ina_id = (request.form.get("ina_id") or "").strip() or None
            student.ub_id = (request.form.get("ub_id") or "").strip() or None
            student.notes = (request.form.get("notes") or "").strip() or None

            class_group_raw = request.form.get("class_group_id")
            if class_group_raw:
                try:
                    class_group_id = int(class_group_raw)
                except (TypeError, ValueError):
                    class_group_id = None
                if class_group_id:
                    new_class_group = ClassGroup.query.get(class_group_id)
                    if new_class_group is not None:
                        student.class_group = new_class_group
            try:
                db.session.commit()
                flash("Fiche étudiant mise à jour", "success")
            except IntegrityError:
                db.session.rollback()
                db.session.refresh(student)
                flash(
                    "Un étudiant portant ce nom existe déjà pour cette classe.",
                    "danger",
                )
        return redirect(url_for("main.student_detail", student_id=student.id))

    return render_template(
        "students/detail.html",
        student=student,
        class_groups=class_groups,
        pathway_choices=STUDENT_PATHWAY_CHOICES,
        phase_options=phase_options,
        group_options=group_options,
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

    class_groups = (
        ClassGroup.query.options(
            selectinload(ClassGroup.students),
            selectinload(ClassGroup.course_links),
        )
        .order_by(ClassGroup.name)
        .all()
    )
    return render_template("classes/list.html", class_groups=class_groups)


@bp.route("/classe/<int:class_id>", methods=["GET", "POST"])
def class_detail(class_id: int):
    class_group = (
        ClassGroup.query.options(
            selectinload(ClassGroup.students),
            selectinload(ClassGroup.course_links).selectinload(CourseClassLink.course),
        )
        .get_or_404(class_id)
    )
    courses = (
        Course.query.order_by(COURSE_TYPE_ORDER_EXPRESSION, Course.name.asc()).all()
    )
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
        elif form_name == "add-student":
            full_name = (request.form.get("full_name") or "").strip()
            email = (request.form.get("email") or "").strip() or None
            notes = request.form.get("notes") or None
            if not full_name:
                flash("Renseignez le nom de l'étudiant.", "warning")
            else:
                student = Student(
                    class_group=class_group,
                    full_name=full_name,
                    email=email,
                    notes=notes,
                )
                db.session.add(student)
                try:
                    db.session.commit()
                    flash("Étudiant ajouté à la classe", "success")
                except IntegrityError:
                    db.session.rollback()
                    flash(
                        "Un étudiant portant ce nom existe déjà pour cette classe.",
                        "warning",
                    )
        elif form_name == "remove-student":
            try:
                student_id = int(request.form.get("student_id", "0"))
            except ValueError:
                student_id = 0
            student = Student.query.filter_by(
                id=student_id, class_group_id=class_group.id
            ).first()
            if not student:
                flash("Étudiant introuvable", "danger")
            else:
                db.session.delete(student)
                db.session.commit()
                flash("Étudiant retiré de la classe", "success")
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
    course_names = CourseName.query.order_by(CourseName.name).all()

    if request.method == "POST":
        form_name = request.form.get("form")
        if form_name == "create":
            course_name_id = request.form.get("course_name_id")
            try:
                course_name = (
                    CourseName.query.get(int(course_name_id)) if course_name_id else None
                )
            except (TypeError, ValueError):
                course_name = None
            if course_name is None:
                flash(
                    "Sélectionnez un nom de cours depuis la configuration.",
                    "danger",
                )
                return redirect(url_for("main.courses_list"))
            course_type = _normalise_course_type(request.form.get("course_type"))
            semester = _normalise_semester(request.form.get("semester"))
            computers_required = _parse_non_negative_int(
                request.form.get("computers_required"), 0
            )
            course = Course(
                name=Course.compose_name(course_type, course_name.name, semester),
                description=request.form.get("description"),
                session_length_hours=int(request.form.get("session_length_hours", 2)),
                course_type=course_type,
                semester=semester,
                configured_name=course_name,
                requires_computers=bool(request.form.get("requires_computers")),
                computers_required=computers_required,
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

    courses = (
        Course.query.order_by(COURSE_TYPE_ORDER_EXPRESSION, Course.name.asc()).all()
    )
    return render_template(
        "courses/list.html",
        courses=courses,
        equipments=equipments,
        softwares=softwares,
        class_groups=class_groups,
        teachers=teachers,
        course_type_labels=COURSE_TYPE_LABELS,
        course_names=course_names,
        semester_choices=SEMESTER_CHOICES,
        default_semester=DEFAULT_SEMESTER,
    )


@bp.route("/generation", methods=["GET", "POST"])
def generation_overview():
    if request.method == "POST":
        action = request.form.get("form")
        courses = (
            Course.query.options(
                selectinload(Course.class_links),
                selectinload(Course.sessions),
                selectinload(Course.generation_logs),
            )
            .order_by(COURSE_TYPE_ORDER_EXPRESSION, Course.name.asc())
            .all()
        )
        if action == "generate":
            total_created = 0
            failures = 0
            for course in courses:
                allowed_ranges = course.allowed_week_ranges
                window_start = allowed_ranges[0][0] if allowed_ranges else None
                window_end = allowed_ranges[-1][1] if allowed_ranges else None
                allowed_payload = (
                    [(start, end) for start, end in allowed_ranges]
                    if allowed_ranges
                    else None
                )
                try:
                    created_sessions = generate_schedule(
                        course,
                        window_start=window_start,
                        window_end=window_end,
                        allowed_weeks=allowed_payload,
                    )
                    db.session.commit()
                    total_created += len(created_sessions)
                except ValueError as exc:
                    db.session.commit()
                    failures += 1
                    current_app.logger.warning(
                        "Automatic generation failed for %s: %s", course.name, exc
                    )
            if total_created:
                flash(f"{total_created} séance(s) générée(s).", "success")
            else:
                flash(
                    "Aucune séance n'a pu être générée automatiquement.",
                    "info",
                )
            if failures:
                flash(
                    f"{failures} cours n'ont pas pu être planifiés. Consultez les recommandations ci-dessous.",
                    "warning",
                )
        elif action == "clear":
            total_sessions = 0
            total_logs = 0
            for course in courses:
                removed_sessions, removed_logs = _clear_course_schedule(course)
                total_sessions += removed_sessions
                total_logs += removed_logs
            db.session.commit()
            if total_sessions:
                flash(
                    f"{total_sessions} séance(s) supprimée(s) et {total_logs} journal(aux) réinitialisé(s).",
                    "success",
                )
            else:
                flash("Aucune séance n'était planifiée.", "info")
        return redirect(url_for("main.generation_overview"))

    search_query = (request.args.get("q") or "").strip()
    selected_statuses = [
        status
        for status in request.args.getlist("status")
        if status in STATUS_BADGES
    ]
    selected_course_type = request.args.get("course_type")
    if selected_course_type not in COURSE_TYPE_LABELS:
        selected_course_type = None
    class_id_raw = request.args.get("class_id")
    try:
        selected_class_id = int(class_id_raw) if class_id_raw else None
    except (TypeError, ValueError):
        selected_class_id = None

    class_groups = ClassGroup.query.order_by(ClassGroup.name.asc()).all()

    courses = (
        Course.query.options(
            selectinload(Course.class_links).selectinload(CourseClassLink.class_group),
            selectinload(Course.sessions),
            selectinload(Course.generation_logs),
        )
        .order_by(COURSE_TYPE_ORDER_EXPRESSION, Course.name.asc())
        .all()
    )

    def _unique(values: Iterable[str | None]) -> list[str]:
        collected: list[str] = []
        for value in values:
            if not value:
                continue
            cleaned = str(value).strip()
            if cleaned and cleaned not in collected:
                collected.append(cleaned)
        return collected

    course_rows: list[dict[str, object]] = []
    for course in courses:
        latest_log = course.latest_generation_log
        required_hours = course.total_required_hours
        scheduled_hours = course.scheduled_hours
        remaining_hours = max(required_hours - scheduled_hours, 0)
        status = _effective_generation_status(
            course,
            latest_log,
            remaining_hours=remaining_hours,
        )
        errors: list[str] = []
        suggestions: list[str] = []
        if latest_log:
            for entry in latest_log.parsed_messages():
                level = str(entry.get("level", "")).lower()
                if level != "error":
                    continue
                errors.append(str(entry.get("message", "")).strip())
                suggestions.extend(entry.get("suggestions", []) or [])

        class_group_ids = [
            link.class_group_id
            for link in course.class_links
            if link.class_group_id is not None
        ]
        course_rows.append(
            {
                "course": course,
                "status": status,
                "latest_log": latest_log,
                "errors": _unique(errors),
                "suggestions": _unique(suggestions),
                "sessions_count": len(course.sessions),
                "scheduled_hours": scheduled_hours,
                "required_hours": required_hours,
                "remaining_hours": remaining_hours,
                "class_labels": ", ".join(
                    sorted(
                        link.class_group.name
                        for link in course.class_links
                        if link.class_group is not None
                    )
                ),
                "class_group_ids": class_group_ids,
            }
        )

    search_term = search_query.lower()
    filtered_rows: list[dict[str, object]] = []
    for row in course_rows:
        course = row["course"]
        if search_term:
            haystack = " ".join(
                filter(
                    None,
                    [
                        course.name.lower(),
                        course.course_type.lower(),
                        row.get("class_labels", "").lower(),
                    ],
                )
            )
            if search_term not in haystack:
                continue
        if selected_statuses and row["status"] not in selected_statuses:
            continue
        if selected_course_type and course.course_type != selected_course_type:
            continue
        if selected_class_id and selected_class_id not in row.get("class_group_ids", []):
            continue
        filtered_rows.append(row)

    total_required_hours = sum(
        row["required_hours"] for row in filtered_rows
    )
    total_scheduled_hours = sum(
        row["scheduled_hours"] for row in filtered_rows
    )
    total_remaining_hours = sum(
        row["remaining_hours"] for row in filtered_rows
    )

    total_courses = len(filtered_rows)
    scheduled_courses = sum(1 for row in filtered_rows if row["sessions_count"])
    error_courses = sum(1 for row in filtered_rows if row["status"] == "error")
    warning_courses = sum(1 for row in filtered_rows if row["status"] == "warning")
    has_active_filters = bool(
        search_query or selected_statuses or selected_course_type or selected_class_id
    )

    status_filter_options = [
        ("error", GENERATION_STATUS_LABELS["error"]),
        ("warning", GENERATION_STATUS_LABELS["warning"]),
        ("success", GENERATION_STATUS_LABELS["success"]),
        ("none", GENERATION_STATUS_LABELS["none"]),
    ]

    return render_template(
        "generation/index.html",
        course_rows=filtered_rows,
        total_courses=total_courses,
        scheduled_courses=scheduled_courses,
        error_courses=error_courses,
        warning_courses=warning_courses,
        total_required_hours=total_required_hours,
        total_scheduled_hours=total_scheduled_hours,
        total_remaining_hours=total_remaining_hours,
        status_labels=GENERATION_STATUS_LABELS,
        status_badges=STATUS_BADGES,
        course_type_labels=COURSE_TYPE_LABELS,
        class_groups=class_groups,
        search_query=search_query,
        selected_statuses=selected_statuses,
        selected_course_type=selected_course_type,
        selected_class_id=selected_class_id,
        has_active_filters=has_active_filters,
        status_filter_options=status_filter_options,
    )


@bp.get("/generation/progress/<string:job_id>")
def schedule_progress_status(job_id: str):
    tracker = progress_registry.get(job_id)
    if tracker is None:
        return jsonify({"error": "Progression introuvable"}), 404
    snapshot = tracker.snapshot()
    if snapshot.total_hours > 0:
        hours_detail = (
            f"{_format_hours(snapshot.completed_hours)} / "
            f"{_format_hours(snapshot.total_hours)} h planifiées"
        )
        if snapshot.sessions_created > 0:
            detail = (
                f"{snapshot.sessions_created} séance(s) planifiée(s) — "
                + hours_detail
            )
        else:
            detail = hours_detail
    elif snapshot.sessions_created > 0:
        detail = f"{snapshot.sessions_created} séance(s) planifiée(s)"
    else:
        detail = None
    detail_parts: List[str] = []
    if snapshot.current_label:
        detail_parts.append(snapshot.current_label)
    if detail:
        detail_parts.append(detail)
    detail_text = " — ".join(detail_parts) if detail_parts else None
    return jsonify(
        {
            "id": snapshot.job_id,
            "label": snapshot.label,
            "state": snapshot.state,
            "percent": snapshot.percent,
            "eta_seconds": snapshot.eta_seconds,
            "sessions_created": snapshot.sessions_created,
            "completed_hours": snapshot.completed_hours,
            "total_hours": snapshot.total_hours,
            "message": snapshot.message,
            "detail": detail_text,
            "finished": snapshot.finished,
        }
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
    course_names = CourseName.query.order_by(CourseName.name).all()
    class_links_map = {link.class_group_id: link for link in course.class_links}

    if request.method == "POST":
        form_name = request.form.get("form")
        if form_name == "update":
            selected_course_name = None
            course_name_id = request.form.get("course_name_id")
            if course_name_id:
                try:
                    selected_course_name = CourseName.query.get(int(course_name_id))
                except (TypeError, ValueError):
                    selected_course_name = None
            base_label = (
                selected_course_name.name
                if selected_course_name
                else course.base_display_name
                or course.name
            )
            course.description = request.form.get("description")
            course.session_length_hours = int(request.form.get("session_length_hours", course.session_length_hours))
            course.course_type = _normalise_course_type(request.form.get("course_type"))
            course.semester = _normalise_semester(request.form.get("semester"))
            course.configured_name = selected_course_name
            course.name = Course.compose_name(
                course.course_type,
                base_label,
                course.semester,
            )
            course.requires_computers = bool(request.form.get("requires_computers"))
            course.computers_required = _parse_non_negative_int(
                request.form.get("computers_required"), course.computers_required
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
            class_ids = {int(cid) for cid in request.form.getlist("classes")}
            selected_teachers = [
                teacher
                for teacher in (
                    Teacher.query.get(int(tid)) for tid in request.form.getlist("teachers")
                )
                if teacher is not None
            ]
            selected_weeks = _parse_week_selection(
                request.form.getlist("allowed_week_starts")
            )

            _sync_simple_relationship(course.equipments, selected_equipments)
            _sync_simple_relationship(course.softwares, selected_softwares)
            _sync_course_class_links(course, class_ids, existing_links=class_links_map)
            _sync_simple_relationship(course.teachers, selected_teachers)
            _sync_course_allowed_weeks(course, (start for start, _ in selected_weeks))
            try:
                db.session.commit()
                flash("Cours mis à jour", "success")
            except IntegrityError:
                db.session.rollback()
                db.session.refresh(course)
                flash("Nom de cours déjà utilisé", "danger")
        elif form_name == "auto-schedule":
            allowed_ranges = course.allowed_week_ranges
            window_start = allowed_ranges[0][0] if allowed_ranges else None
            window_end = allowed_ranges[-1][1] if allowed_ranges else None
            allowed_payload = (
                [(start, end) for start, end in allowed_ranges]
                if allowed_ranges
                else None
            )
            if _wants_json_response():
                tracker = _enqueue_course_schedule(
                    course,
                    window_start=window_start,
                    window_end=window_end,
                    allowed_weeks=allowed_payload,
                )
                response = {
                    "job_id": tracker.job_id,
                    "status_url": url_for(
                        "main.schedule_progress_status", job_id=tracker.job_id
                    ),
                    "redirect_url": url_for("main.course_detail", course_id=course.id),
                    "label": course.name,
                }
                return jsonify(response), 202
            try:
                created_sessions = generate_schedule(
                    course,
                    window_start=window_start,
                    window_end=window_end,
                    allowed_weeks=allowed_payload,
                )
                db.session.commit()
                if created_sessions:
                    flash(f"{len(created_sessions)} séance(s) générée(s)", "success")
                else:
                    flash("Aucune séance générée", "info")
            except ValueError as exc:
                db.session.commit()
                flash(str(exc), "danger")
        elif form_name == "update-class-teachers":
            allowed_teacher_ids = {teacher.id for teacher in course.teachers if teacher.id}
            if course.is_cm:
                teacher = _parse_teacher_selection(
                    request.form.get("course_teacher_all"),
                    allowed_ids=allowed_teacher_ids,
                )
                for link in course.class_links:
                    link.teacher_a = teacher
                    link.teacher_b = None
            elif course.is_sae:
                assignments: list[tuple[CourseClassLink, Teacher, Teacher]] = []
                for link in course.class_links:
                    teacher_a = _parse_teacher_selection(
                        request.form.get(
                            f"class_link_teacher_a_{link.class_group_id}"
                        ),
                        allowed_ids=allowed_teacher_ids,
                    )
                    teacher_b = _parse_teacher_selection(
                        request.form.get(
                            f"class_link_teacher_b_{link.class_group_id}"
                        ),
                        allowed_ids=allowed_teacher_ids,
                    )
                    if teacher_a is None or teacher_b is None:
                        db.session.rollback()
                        flash(
                            "Pour les SAE, deux enseignants doivent être attribués à chaque classe.",
                            "danger",
                        )
                        return redirect(
                            url_for("main.course_detail", course_id=course_id)
                        )
                    if teacher_a.id == teacher_b.id:
                        db.session.rollback()
                        flash(
                            "Pour les SAE, les deux enseignants doivent être distincts.",
                            "danger",
                        )
                        return redirect(
                            url_for("main.course_detail", course_id=course_id)
                        )
                    assignments.append((link, teacher_a, teacher_b))
                for link, teacher_a, teacher_b in assignments:
                    link.teacher_a = teacher_a
                    link.teacher_b = teacher_b
            else:
                for link in course.class_links:
                    if link.group_count == 2:
                        teacher_a = _parse_teacher_selection(
                            request.form.get(
                                f"class_link_teacher_{link.class_group_id}_A"
                            ),
                            allowed_ids=allowed_teacher_ids,
                        )
                        teacher_b = _parse_teacher_selection(
                            request.form.get(
                                f"class_link_teacher_{link.class_group_id}_B"
                            ),
                            allowed_ids=allowed_teacher_ids,
                        )
                        link.teacher_a = teacher_a
                        link.teacher_b = teacher_b
                    else:
                        teacher = _parse_teacher_selection(
                            request.form.get(
                                f"class_link_teacher_{link.class_group_id}"
                            ),
                            allowed_ids=allowed_teacher_ids,
                        )
                        link.teacher_a = teacher
                        link.teacher_b = None
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
            class_group_labels: dict[int, str | None] | None = None
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
                    flash("Choisissez un sous-groupe correspondant à la configuration", "danger")
                    return redirect(url_for("main.course_detail", course_id=course_id))
                class_groups = [class_group]
                primary_class = class_group
                class_group_labels = {class_group.id: subgroup_label}
            error_message = _validate_session_constraints(
                course,
                teacher,
                room,
                class_groups,
                start_dt,
                end_dt,
                class_group_labels=class_group_labels,
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
            removed, _ = _clear_course_schedule(course)
            db.session.commit()
            if removed:
                flash("Toutes les séances de ce cours ont été supprimées.", "success")
            else:
                flash("Aucune séance n'était planifiée pour ce cours.", "info")
        return redirect(url_for("main.course_detail", course_id=course_id))

    events = sessions_to_grouped_events(course.sessions)
    latest_generation_log = (
        CourseScheduleLog.query.filter_by(course_id=course.id)
        .order_by(CourseScheduleLog.created_at.desc())
        .first()
    )

    available_teachers = sorted(
        course.teachers,
        key=lambda teacher: (teacher.name or "").lower(),
    )

    teacher_duos_by_class: dict[int, tuple[Teacher, Teacher, float]] = {}
    teacher_duos_average_hours: float | None = None
    if course.course_type == "TP" and available_teachers:
        teacher_duos_by_class = recommend_teacher_duos_for_classes(
            course.class_links,
            available_teachers,
        )
        if teacher_duos_by_class:
            total_overlap = sum(pair[2] for pair in teacher_duos_by_class.values())
            teacher_duos_average_hours = total_overlap / len(teacher_duos_by_class)

    closing_spans = _closing_period_spans()

    week_ranges = _semester_week_ranges(course.semester)

    selected_course_week_values = {
        allowed.week_start.isoformat()
        for allowed in course.allowed_weeks
        if not _is_week_closed(allowed.week_start, allowed.week_end, closing_spans)
    }

    known_starts = {start for start, _ in week_ranges}
    for allowed in course.allowed_weeks:
        if _is_week_closed(allowed.week_start, allowed.week_end, closing_spans):
            continue
        if allowed.week_start not in known_starts:
            week_ranges.append((allowed.week_start, allowed.week_end))
            known_starts.add(allowed.week_start)

    week_ranges.sort(key=lambda span: span[0])

    course_week_options = [
        {"value": start.isoformat(), "label": _week_label(start, end)}
        for start, end in week_ranges
    ]
    selected_course_week_labels = [
        _week_label(allowed.week_start, allowed.week_end)
        for allowed in course.allowed_weeks
        if not _is_week_closed(allowed.week_start, allowed.week_end, closing_spans)
    ]

    remaining_hours = max(course.total_required_hours - course.scheduled_hours, 0)
    generation_display_status = _effective_generation_status(
        course,
        latest_generation_log,
        remaining_hours=remaining_hours,
    )

    return render_template(
        "courses/detail.html",
        course=course,
        equipments=equipments,
        softwares=softwares,
        teachers=teachers,
        rooms=rooms,
        class_groups=class_groups,
        class_links_map=class_links_map,
        course_names=course_names,
        semester_choices=SEMESTER_CHOICES,
        default_semester=DEFAULT_SEMESTER,
        available_teachers=available_teachers,
        events_json=json.dumps(events, ensure_ascii=False),
        start_times=START_TIMES,
        latest_generation_log=latest_generation_log,
        status_labels=GENERATION_STATUS_LABELS,
        status_badges=STATUS_BADGES,
        level_badges=LEVEL_BADGES,
        course_week_options=course_week_options,
        selected_course_week_values=selected_course_week_values,
        selected_course_week_labels=selected_course_week_labels,
        course_remaining_hours=remaining_hours,
        generation_display_status=generation_display_status,
        teacher_duos_by_class=teacher_duos_by_class,
        teacher_duos_average_hours=teacher_duos_average_hours,
    )


@bp.route("/equipement", methods=["GET", "POST"])
def equipment_list():
    target = url_for("main.configuration") + "#config-equipments"
    return redirect(target)


@bp.route("/logiciel", methods=["GET", "POST"])
def software_list():
    target = url_for("main.configuration") + "#config-softwares"
    return redirect(target)


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
    class_group_labels: dict[int, str | None] = {}
    if session.class_group_id is not None:
        class_group_labels[session.class_group_id] = session.subgroup_label
    for attendee in attendee_classes:
        if attendee is None or attendee.id is None:
            continue
        class_group_labels.setdefault(attendee.id, None)
    error_message = _validate_session_constraints(
        session.course,
        session.teacher,
        session.room,
        attendee_classes,
        start_dt,
        end_dt,
        ignore_session_id=session.id,
        class_group_labels=class_group_labels or None,
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


def _wants_json_response() -> bool:
    if request.headers.get("X-Requested-With", "").lower() == "xmlhttprequest":
        return True
    if request.is_json:
        return True
    accept = request.accept_mimetypes
    if not accept:
        return False
    best = accept.best
    if best == "application/json":
        return True
    json_quality = accept["application/json"]
    html_quality = accept["text/html"]
    return json_quality and json_quality >= html_quality


def _run_course_schedule_job(
    app,
    tracker_id: str,
    course_id: int,
    window_start: date | None,
    window_end: date | None,
    allowed_weeks: list[tuple[date, date]] | None,
) -> None:
    with app.app_context():
        tracker = progress_registry.get(tracker_id)
        if tracker is None:
            return
        try:
            course = Course.query.get(course_id)
            if course is None:
                tracker.fail("Cours introuvable.")
                return
            created_sessions = generate_schedule(
                course,
                window_start=window_start,
                window_end=window_end,
                allowed_weeks=allowed_weeks,
                progress=tracker,
            )
            db.session.commit()
            if not tracker.is_finished():
                tracker.complete(
                    f"{len(created_sessions)} séance(s) générée(s)"
                )
        except ValueError as exc:
            db.session.rollback()
            tracker.fail(str(exc))
        except Exception:  # pragma: no cover - defensive logging
            db.session.rollback()
            tracker.fail("Erreur inattendue lors de la génération.")
            current_app.logger.exception(
                "Automatic scheduling failed for course %s", course_id
            )
        finally:
            db.session.remove()


def _enqueue_course_schedule(
    course: Course,
    *,
    window_start: date | None,
    window_end: date | None,
    allowed_weeks: list[tuple[date, date]] | None,
) -> ScheduleProgressTracker:
    app = current_app._get_current_object()
    tracker = progress_registry.create(course.name)
    progress_registry.purge()
    thread = threading.Thread(
        target=_run_course_schedule_job,
        args=(app, tracker.job_id, course.id, window_start, window_end, allowed_weeks),
        daemon=True,
    )
    thread.start()
    return tracker


def _run_bulk_schedule_job(app, tracker_id: str) -> None:
    with app.app_context():
        tracker = progress_registry.get(tracker_id)
        if tracker is None:
            return
        try:
            courses = (
                Course.query.order_by(COURSE_TYPE_ORDER_EXPRESSION, Course.name.asc())
                .options(
                    selectinload(Course.class_links),
                    selectinload(Course.sessions),
                )
                .all()
            )
            total_hours = sum(
                max(course.total_required_hours - course.scheduled_hours, 0)
                for course in courses
            )
            tracker.initialise(total_hours)

            total_created = 0
            errors: list[str] = []

            for course in courses:
                allowed_ranges = course.allowed_week_ranges
                window_start = allowed_ranges[0][0] if allowed_ranges else None
                window_end = allowed_ranges[-1][1] if allowed_ranges else None
                allowed_payload = (
                    [(start, end) for start, end in allowed_ranges]
                    if allowed_ranges
                    else None
                )
                slice_progress = tracker.create_slice(
                    label=f"Planification de {course.name}"
                )
                try:
                    created_sessions = generate_schedule(
                        course,
                        window_start=window_start,
                        window_end=window_end,
                        allowed_weeks=allowed_payload,
                        progress=slice_progress,
                    )
                except ValueError as exc:
                    errors.append(f"{course.name} : {exc}")
                    tracker.set_current_label(None)
                    db.session.commit()
                    continue
                total_created += len(created_sessions)
                db.session.commit()

            if errors:
                current_app.logger.warning(
                    "Bulk scheduling completed with warnings: %s", errors
                )

            if total_created:
                summary = f"{total_created} séance(s) générée(s)"
            else:
                summary = (
                    "Aucune séance n'a pu être générée avec les contraintes actuelles."
                )

            if errors:
                summary = f"{summary} — {len(errors)} cours en erreur"

            tracker.complete(summary)
        except Exception:
            db.session.rollback()
            tracker.fail("Erreur inattendue lors de la génération globale.")
            current_app.logger.exception("Automatic bulk scheduling failed")
        finally:
            db.session.remove()


def _enqueue_bulk_schedule() -> ScheduleProgressTracker:
    app = current_app._get_current_object()
    tracker = progress_registry.create("Génération globale")
    progress_registry.purge()
    thread = threading.Thread(
        target=_run_bulk_schedule_job,
        args=(app, tracker.job_id),
        daemon=True,
    )
    thread.start()
    return tracker

