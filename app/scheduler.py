from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Iterable, List, Optional, TypeVar

from flask import current_app

from . import db
from .models import ClassGroup, Course, CourseClassLink, Room, Session, Teacher

# Working windows respecting pauses
WORKING_WINDOWS: List[tuple[time, time]] = [
    (time(8, 0), time(10, 0)),
    (time(10, 15), time(12, 15)),
    (time(13, 30), time(15, 30)),
    (time(15, 45), time(17, 45)),
]

SCHEDULE_SLOTS: List[tuple[time, time]] = [
    (time(8, 0), time(9, 0)),
    (time(9, 0), time(10, 0)),
    (time(10, 15), time(11, 15)),
    (time(11, 15), time(12, 15)),
    (time(13, 30), time(14, 30)),
    (time(14, 30), time(15, 30)),
    (time(15, 45), time(16, 45)),
    (time(16, 45), time(17, 45)),
]

START_TIMES: List[time] = [slot_start for slot_start, _ in SCHEDULE_SLOTS]


T = TypeVar("T")


def _spread_sequence(items: Iterable[T]) -> list[T]:
    ordered = list(items)
    spread: list[T] = []
    left = 0
    right = len(ordered) - 1
    while left <= right:
        spread.append(ordered[left])
        left += 1
        if left <= right:
            spread.append(ordered[right])
            right -= 1
    return spread


def daterange(start: date, end: date) -> Iterable[date]:
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    return max(a_start, b_start) < min(a_end, b_end)


def fits_in_windows(start: time, end: time) -> bool:
    for window_start, window_end in WORKING_WINDOWS:
        if window_start <= start and end <= window_end:
            return True
    return False


def find_available_room(
    course: Course,
    start: datetime,
    end: datetime,
    *,
    required_capacity: int | None = None,
) -> Optional[Room]:
    rooms = Room.query.order_by(Room.capacity.asc()).all()
    required_students = required_capacity or 1
    for room in rooms:
        if room.capacity < required_students:
            continue
        if course.requires_computers and room.computers <= 0:
            continue
        if any(eq not in room.equipments for eq in course.equipments):
            continue
        if any(sw not in room.softwares for sw in course.softwares):
            continue
        conflict = False
        for session in room.sessions:
            if overlaps(session.start_time, session.end_time, start, end):
                conflict = True
                break
        if not conflict:
            return room
    return None


def find_available_teacher(
    course: Course,
    start: datetime,
    end: datetime,
    *,
    link: CourseClassLink | None = None,
    subgroup_label: str | None = None,
) -> Optional[Teacher]:
    preferred: list[Teacher] = []
    if link is not None:
        assigned = link.teacher_for_label(subgroup_label)
        if assigned is not None:
            preferred.append(assigned)

    if course.teachers:
        fallback_pool = list(course.teachers)
    else:
        fallback_pool = Teacher.query.all()

    candidates = preferred + [teacher for teacher in fallback_pool if teacher not in preferred]
    for teacher in sorted(candidates, key=lambda t: t.name.lower()):
        if not teacher.is_available_during(start, end):
            continue
        if any(overlaps(s.start_time, s.end_time, start, end) for s in teacher.sessions):
            continue
        return teacher
    return None


def _normalise_label(label: str | None) -> str:
    return (label or "").upper()


def _class_sessions_needed(
    course: Course, class_group: ClassGroup, subgroup_label: str | None = None
) -> int:
    target_label = _normalise_label(subgroup_label)
    existing = sum(
        1
        for session in course.sessions
        if session.class_group_id == class_group.id
        and _normalise_label(session.subgroup_label) == target_label
    )
    required_total = course.sessions_required
    return max(required_total - existing, 0)


def _day_search_order(available_days: list[date], anchor_index: int) -> list[date]:
    order: list[date] = []
    if not available_days:
        return order
    anchor_index = max(0, min(anchor_index, len(available_days) - 1))
    order.append(available_days[anchor_index])
    step = 1
    while len(order) < len(available_days):
        if anchor_index + step < len(available_days):
            order.append(available_days[anchor_index + step])
        if anchor_index - step >= 0:
            order.append(available_days[anchor_index - step])
        step += 1
    return order


def _resolve_schedule_window(
    course: Course, window_start: date | None, window_end: date | None
) -> tuple[date, date]:
    start_candidates = [value for value in (course.start_date, window_start) if value]
    end_candidates = [value for value in (course.end_date, window_end) if value]
    if not start_candidates or not end_candidates:
        raise ValueError(
            "Définissez des dates de début et de fin pour le cours ou indiquez une période de planification."
        )
    start = max(start_candidates)
    end = min(end_candidates)
    if start > end:
        raise ValueError(
            "La période choisie n'intersecte pas la fenêtre du cours."
        )
    return start, end


def generate_schedule(
    course: Course,
    *,
    window_start: date | None = None,
    window_end: date | None = None,
) -> list[Session]:
    schedule_start, schedule_end = _resolve_schedule_window(course, window_start, window_end)
    if not course.classes:
        raise ValueError("Associez au moins une classe au cours avant de planifier.")

    created_sessions: list[Session] = []

    slot_length_hours = course.session_length_hours
    slot_length = timedelta(hours=slot_length_hours)

    links = sorted(course.class_links, key=lambda link: link.class_group.name.lower())
    for link in links:
        class_group = link.class_group
        for subgroup_label in link.group_labels():
            sessions_to_create = _class_sessions_needed(course, class_group, subgroup_label)
            if sessions_to_create == 0:
                continue
            available_days = [
                day
                for day in sorted(daterange(schedule_start, schedule_end))
                if day.weekday() < 5 and class_group.is_available_on(day)
            ]
            if not available_days:
                current_app.logger.warning(
                    "Aucune journée disponible pour %s (%s) entre %s et %s",
                    course.name,
                    class_group.name,
                    schedule_start,
                    schedule_end,
                )
                continue

            start_time_order = _spread_sequence(START_TIMES)
            scheduled_count = 0
            while scheduled_count < sessions_to_create:
                anchor_ratio = (scheduled_count + 0.5) / sessions_to_create
                anchor_index = int(anchor_ratio * len(available_days))
                if anchor_index >= len(available_days):
                    anchor_index = len(available_days) - 1

                placed = False
                for day in _day_search_order(available_days, anchor_index):
                    for offset in range(len(start_time_order)):
                        slot_start_time = start_time_order[(scheduled_count + offset) % len(start_time_order)]
                        start_dt = datetime.combine(day, slot_start_time)
                        end_dt = start_dt + slot_length
                        if not fits_in_windows(start_dt.time(), end_dt.time()):
                            continue
                        if not class_group.is_available_during(start_dt, end_dt):
                            continue
                        teacher = find_available_teacher(
                            course,
                            start_dt,
                            end_dt,
                            link=link,
                            subgroup_label=subgroup_label,
                        )
                        if not teacher:
                            continue
                        required_capacity = course.capacity_needed_for(class_group)
                        room = find_available_room(
                            course,
                            start_dt,
                            end_dt,
                            required_capacity=required_capacity,
                        )
                        if not room:
                            continue
                        session = Session(
                            course=course,
                            teacher=teacher,
                            room=room,
                            class_group=class_group,
                            subgroup_label=subgroup_label,
                            start_time=start_dt,
                            end_time=end_dt,
                        )
                        db.session.add(session)
                        created_sessions.append(session)
                        scheduled_count += 1
                        placed = True
                        break
                    if placed:
                        break
                if not placed:
                    break

            remaining = sessions_to_create - scheduled_count
            if remaining > 0:
                current_app.logger.warning(
                    "Unable to schedule %s sessions for %s (%s)",
                    remaining,
                    course.name,
                    class_group.name,
                )
    return created_sessions
