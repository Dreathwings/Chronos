from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Iterable, List, Optional, TypeVar

from flask import current_app

from . import db
from .models import ClassGroup, Course, Room, Session, Teacher

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


def teacher_hours_in_week(teacher: Teacher, week_start: date) -> float:
    week_end = week_start + timedelta(days=7)
    total = 0.0
    for session in teacher.sessions:
        if week_start <= session.start_time.date() < week_end:
            delta = session.end_time - session.start_time
            total += delta.total_seconds() / 3600
    return total


def find_available_room(course: Course, start: datetime, end: datetime) -> Optional[Room]:
    rooms = Room.query.order_by(Room.capacity.asc()).all()
    for room in rooms:
        if room.capacity < course.expected_students:
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


def find_available_teacher(course: Course, start: datetime, end: datetime) -> Optional[Teacher]:
    candidate_teachers = course.teachers if course.teachers else Teacher.query.all()
    for teacher in sorted(candidate_teachers, key=lambda t: t.max_hours_per_week):
        if not teacher.is_available_during(start, end):
            continue
        if any(overlaps(s.start_time, s.end_time, start, end) for s in teacher.sessions):
            continue
        week_start = start.date() - timedelta(days=start.weekday())
        if teacher_hours_in_week(teacher, week_start) + course.session_length_hours > teacher.max_hours_per_week:
            continue
        return teacher
    return None


def _class_sessions_needed(course: Course, class_group: ClassGroup) -> int:
    existing = sum(1 for session in course.sessions if session.class_group_id == class_group.id)
    return max(course.sessions_required - existing, 0)


def generate_schedule(course: Course) -> list[Session]:
    if not course.start_date or not course.end_date:
        raise ValueError("Course must have start and end dates to schedule automatically.")
    if not course.classes:
        raise ValueError("Associez au moins une classe au cours avant de planifier.")

    created_sessions: list[Session] = []

    slot_length_hours = course.session_length_hours
    slot_length = timedelta(hours=slot_length_hours)

    priority_days = _spread_sequence(sorted(daterange(course.start_date, course.end_date)))
    priority_start_times = _spread_sequence(START_TIMES)

    for class_group in sorted(course.classes, key=lambda c: c.name.lower()):
        sessions_to_create = _class_sessions_needed(course, class_group)
        if sessions_to_create == 0:
            continue
        for day in priority_days:
            if sessions_to_create == 0:
                break
            if day.weekday() >= 5:
                continue
            if not class_group.is_available_on(day):
                continue
            for slot_start_time in priority_start_times:
                start_dt = datetime.combine(day, slot_start_time)
                end_dt = start_dt + slot_length
                if not fits_in_windows(start_dt.time(), end_dt.time()):
                    continue
                if not class_group.is_available_during(start_dt, end_dt):
                    continue
                teacher = find_available_teacher(course, start_dt, end_dt)
                if not teacher:
                    continue
                room = find_available_room(course, start_dt, end_dt)
                if not room:
                    continue
                session = Session(
                    course=course,
                    teacher=teacher,
                    room=room,
                    class_group=class_group,
                    start_time=start_dt,
                    end_time=end_dt,
                )
                db.session.add(session)
                created_sessions.append(session)
                sessions_to_create -= 1
                if sessions_to_create == 0:
                    break
        if sessions_to_create > 0:
            current_app.logger.warning(
                "Unable to schedule %s sessions for %s (%s)",
                sessions_to_create,
                course.name,
                class_group.name,
            )
    return created_sessions
