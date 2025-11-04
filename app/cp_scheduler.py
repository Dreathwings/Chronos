from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Iterable, List, Optional, Sequence

from pydantic import ValidationError

from chronos.scheduler.api import generate_schedule as run_cp_solver
from chronos.scheduler.config import DEFAULT_CONFIG

from . import db
from .models import ClassGroup, Course, Room, Session, Teacher
from .scheduler import (
    SCHEDULE_SLOTS,
    NullScheduleProgress,
    ScheduleProgress,
    ScheduleReporter,
    _abort_if_cancelled,
    _closed_days_between,
    _resolve_schedule_window,
    daterange,
)


@dataclass
class _CourseContext:
    teacher_lookup: dict[str, Teacher]
    group_lookup: dict[str, ClassGroup]
    room_lookup: dict[str, Room]


def _collect_allowed_days(
    course: Course,
    window_start: date,
    window_end: date,
    allowed_weeks: Optional[Iterable[Sequence[date]]],
) -> List[date]:
    allowed: set[date] = set()
    if allowed_weeks:
        for entry in allowed_weeks:
            if len(entry) < 2:
                continue
            week_start = entry[0]
            week_end = entry[1]
            span_start = max(window_start, week_start)
            span_end = min(window_end, week_end)
            if span_end < span_start:
                continue
            for day in daterange(span_start, span_end):
                allowed.add(day)
    else:
        for day in daterange(window_start, window_end):
            allowed.add(day)

    closed_days = _closed_days_between(window_start, window_end)
    final_days: List[date] = []
    for day in sorted(allowed):
        if day.weekday() >= 5:
            continue
        if day in closed_days:
            continue
        final_days.append(day)
    return final_days


def _teacher_candidates(course: Course) -> List[Teacher]:
    candidates: list[Teacher] = []
    seen: set[int] = set()

    for teacher in course.teachers:
        if teacher and teacher.id not in seen:
            seen.add(teacher.id)
            candidates.append(teacher)

    for link in course.class_links:
        for teacher in link.assigned_teachers():
            if teacher and teacher.id not in seen:
                seen.add(teacher.id)
                candidates.append(teacher)

    return candidates


def _build_course_payload(
    course: Course,
    *,
    window_start: date,
    window_end: date,
    allowed_weeks: Optional[Iterable[Sequence[date]]],
) -> tuple[dict, _CourseContext]:
    allowed_days = _collect_allowed_days(course, window_start, window_end, allowed_weeks)
    if not allowed_days:
        raise ValueError(
            "Aucun jour ouvré disponible pour cette période de planification."
        )

    time_grid: list[dict[str, object]] = []
    for day in allowed_days:
        for slot_start, slot_end in SCHEDULE_SLOTS:
            slot_id = f"{day.isoformat()}_{slot_start.strftime('%H%M')}"
            time_grid.append(
                {
                    "slot_id": slot_id,
                    "day": day,
                    "start": slot_start,
                    "end": slot_end,
                }
            )

    if not time_grid:
        raise ValueError(
            "Aucun créneau horaire n'est disponible pour les semaines autorisées."
        )

    teachers = _teacher_candidates(course)
    if not teachers:
        raise ValueError(
            "Aucun enseignant n'est associé à ce cours pour la génération automatique."
        )

    teacher_entries: list[dict[str, object]] = []
    teacher_lookup: dict[str, Teacher] = {}
    course_type = (course.course_type or "TD").upper()
    if course_type not in {"CM", "TD", "TP"}:
        course_type = "TD"

    for teacher in teachers:
        available_slots: list[str] = []
        for slot in time_grid:
            slot_day = slot["day"]
            slot_start = slot["start"]
            slot_end = slot["end"]
            start_dt = datetime.combine(slot_day, slot_start)  # type: ignore[arg-type]
            end_dt = datetime.combine(slot_day, slot_end)  # type: ignore[arg-type]
            if teacher.is_available_during(start_dt, end_dt):
                available_slots.append(slot["slot_id"])
        if not available_slots:
            continue
        teacher_id = str(teacher.id)
        teacher_lookup[teacher_id] = teacher
        teacher_entries.append(
            {
                "teacher_id": teacher_id,
                "name": teacher.name,
                "can_teach": [
                    {
                        "module_id": str(course.id),
                        "types": [course_type],
                    }
                ],
                "availability": available_slots,
                "hard_unavailability": [],
                "preferred_slots": [],
                "disliked_slots": [],
            }
        )

    if not teacher_entries:
        raise ValueError(
            "Aucun enseignant n'est disponible sur les créneaux proposés."
        )

    group_entries: list[dict[str, object]] = []
    group_lookup: dict[str, ClassGroup] = {}
    group_slots: list[set[str]] = []
    for link in course.class_links:
        group = link.class_group
        if group is None or group.id is None:
            continue
        group_id = str(group.id)
        group_lookup[group_id] = group
        group_entries.append(
            {
                "group_id": group_id,
                "name": group.name,
                "size": group.size or 0,
                "incompatible_with": [],
            }
        )
        available = set()
        for slot in time_grid:
            slot_day = slot["day"]
            slot_start = slot["start"]
            slot_end = slot["end"]
            start_dt = datetime.combine(slot_day, slot_start)  # type: ignore[arg-type]
            end_dt = datetime.combine(slot_day, slot_end)  # type: ignore[arg-type]
            if group.is_available_during(start_dt, end_dt):
                available.add(slot["slot_id"])
        if not available:
            raise ValueError(
                f"La classe {group.name} n'a aucun créneau disponible sur la période."
            )
        group_slots.append(available)

    if not group_entries:
        raise ValueError("Aucune classe n'est associée à ce cours.")

    allowed_slot_set = set.intersection(*group_slots) if group_slots else set()
    if not allowed_slot_set:
        raise ValueError(
            "Aucun créneau commun n'est disponible pour toutes les classes associées."
        )

    required_equipment = {equipment.name for equipment in course.equipments}
    capacity_needed = 0
    for link in course.class_links:
        if link.class_group is None:
            continue
        capacity_needed = max(
            capacity_needed,
            course.capacity_needed_for(link.class_group),
        )
    if capacity_needed <= 0:
        capacity_needed = max(course.session_group_factor * 10, 10)

    rooms: list[dict[str, object]] = []
    room_lookup: dict[str, Room] = {}
    computers_required = course.required_computer_posts()
    for room in Room.query.order_by(Room.name.asc()).all():
        if room.id is None:
            continue
        if room.capacity < capacity_needed:
            continue
        if course.requires_computers and room.computers < computers_required:
            continue
        room_equipment = {equipment.name for equipment in room.equipments}
        if not required_equipment.issubset(room_equipment):
            continue
        room_id = str(room.id)
        room_lookup[room_id] = room
        rooms.append(
            {
                "room_id": room_id,
                "name": room.name,
                "capacity": room.capacity,
                "equipment": sorted(room_equipment),
            }
        )

    if not rooms:
        raise ValueError("Aucune salle compatible n'est disponible pour ce cours.")

    duration_minutes = int(max(course.session_length_hours or 1, 1) * 60)
    total_units = max(int(course.sessions_required or 0), 0)
    if total_units <= 0:
        raise ValueError("Le volume de séances à planifier est nul.")

    course_entry = {
        "course_id": str(course.id),
        "module_id": str(course.id),
        "type": course_type,
        "duration_minutes": duration_minutes,
        "total_units": total_units,
        "groups": [entry["group_id"] for entry in group_entries],
        "allowed_time_slots": sorted(allowed_slot_set),
        "precedence": [],
        "preferred_slots": [],
        "forbidden_slots": [],
        "required_equipment": sorted(required_equipment),
    }

    solver_config = DEFAULT_CONFIG.solver
    payload = {
        "time_grid": time_grid,
        "teachers": teacher_entries,
        "groups": group_entries,
        "rooms": rooms,
        "courses": [course_entry],
        "global_rules": {
            "forbidden_slots": [],
            "lunch_start": time(hour=12),
            "lunch_end": time(hour=14),
            "lunch_break_minutes": 60,
            "daily_amplitude_minutes": 12 * 60,
        },
        "weights": DEFAULT_CONFIG.weights.as_dict(),
        "limits": {
            "time_limit_seconds": solver_config.time_limit_seconds,
            "random_seed": solver_config.random_seed,
            "num_solutions": solver_config.max_solutions,
            "num_search_workers": solver_config.num_search_workers,
        },
    }

    context = _CourseContext(
        teacher_lookup=teacher_lookup,
        group_lookup=group_lookup,
        room_lookup=room_lookup,
    )
    return payload, context


def _persist_sessions(
    course: Course,
    result: dict,
    context: _CourseContext,
    reporter: ScheduleReporter,
) -> list[Session]:
    for session in list(course.sessions):
        db.session.delete(session)

    created_sessions: list[Session] = []

    def _room_is_available(room: Room, start_dt: datetime, end_dt: datetime) -> bool:
        for existing in room.sessions:
            if max(existing.start_time, start_dt) < min(existing.end_time, end_dt):
                return False
        for planned in created_sessions:
            if (
                planned.room_id == room.id
                and max(planned.start_time, start_dt) < min(planned.end_time, end_dt)
            ):
                return False
        return True

    for entry in result.get("sessions", []):
        if entry.get("course_id") != str(course.id):
            continue
        teacher = context.teacher_lookup.get(str(entry.get("teacher_id")))
        group = context.group_lookup.get(str(entry.get("group_id")))
        room = context.room_lookup.get(str(entry.get("room_id")))
        if not teacher or not group or not room:
            continue
        session_date = entry.get("date")
        start_time = entry.get("start")
        end_time = entry.get("end")
        if not isinstance(session_date, date) or not isinstance(start_time, time) or not isinstance(end_time, time):
            continue
        start_dt = datetime.combine(session_date, start_time)
        end_dt = datetime.combine(session_date, end_time)
        if not _room_is_available(room, start_dt, end_dt):
            reporter.warning(
                f"Créneau ignoré : la salle {room.name} est déjà réservée sur ce créneau."
            )
            continue
        session = Session(
            course=course,
            teacher=teacher,
            room=room,
            class_group=group,
            start_time=start_dt,
            end_time=end_dt,
        )
        db.session.add(session)
        created_sessions.append(session)
        reporter.session_created(session)
    return created_sessions


def generate_schedule(
    course: Course,
    *,
    window_start: date | None = None,
    window_end: date | None = None,
    allowed_weeks: Iterable[Sequence[date]] | None = None,
    progress: ScheduleProgress | None = None,
    occurrence_limit: int | None = None,
    current_week: date | None = None,
    allow_week_rollover: bool = True,
) -> list[Session]:
    progress = progress or NullScheduleProgress()
    _abort_if_cancelled(progress)
    reporter = ScheduleReporter(course)

    base_start = window_start
    base_end = window_end
    if allowed_weeks:
        spans = [tuple(entry[:2]) for entry in allowed_weeks if len(entry) >= 2]
        if spans:
            base_start = spans[0][0]
            base_end = spans[-1][1]

    window_start, window_end = _resolve_schedule_window(
        course,
        base_start,
        base_end,
    )
    reporter.set_window(window_start, window_end)

    payload, context = _build_course_payload(
        course,
        window_start=window_start,
        window_end=window_end,
        allowed_weeks=allowed_weeks,
    )

    total_units = payload["courses"][0]["total_units"]
    if occurrence_limit is not None:
        try:
            limit_value = max(int(occurrence_limit), 0)
        except (TypeError, ValueError):
            limit_value = 0
        if limit_value == 0:
            reporter.info("Aucune séance supplémentaire demandée.")
            reporter.finalise(0)
            return []
        payload["courses"][0]["total_units"] = min(total_units, limit_value)

    try:
        output = run_cp_solver(payload)
    except ValidationError as exc:
        reporter.error("Données invalides pour le solveur CP-SAT.")
        reporter.finalise(0)
        raise ValueError(str(exc)) from exc
    except ValueError as exc:
        reporter.error(str(exc))
        reporter.finalise(0)
        raise

    metrics = output.get("metrics", {})
    if metrics:
        status = metrics.get("status")
        if status:
            reporter.info(f"Solveur CP-SAT : statut {status}")
        objective = metrics.get("objective_value")
        best_bound = metrics.get("best_bound")
        if objective is not None and best_bound is not None:
            reporter.info(
                f"Objectif {objective:.0f} (borne {best_bound:.0f})"
            )

    created_sessions = _persist_sessions(course, output, context, reporter)
    log = reporter.finalise(len(created_sessions))

    if metrics:
        messages = log.parsed_messages()
        metrics_entry = {
            "level": "info",
            "message": json.dumps(metrics, ensure_ascii=False),
        }
        messages.append(metrics_entry)
        log.messages = json.dumps(messages, ensure_ascii=False)

    return created_sessions
