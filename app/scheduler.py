from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Iterable

from dateutil import rrule
from ortools.sat.python import cp_model

from . import db
from .models import Course, CourseSession, Room, Teacher


SLOT_DEFINITION = [
    (time(8, 0), time(9, 0)),
    (time(9, 0), time(10, 0)),
    (time(10, 15), time(11, 15)),
    (time(11, 30), time(12, 30)),
    (time(13, 45), time(14, 45)),
    (time(15, 30), time(16, 30)),
    (time(16, 45), time(17, 45)),
]


@dataclass(frozen=True)
class Slot:
    index: int
    start: datetime
    end: datetime


def _daterange(start: date, days: int) -> Iterable[date]:
    for dt in rrule.rrule(rrule.DAILY, dtstart=start, count=days):
        yield dt.date()


def generate_slots(start_day: date | None = None, days: int = 5) -> list[Slot]:
    start_day = start_day or date.today()
    slots: list[Slot] = []
    index = 0
    for current_day in _daterange(start_day, days):
        for start_time, end_time in SLOT_DEFINITION:
            start_dt = datetime.combine(current_day, start_time)
            end_dt = datetime.combine(current_day, end_time)
            slots.append(Slot(index=index, start=start_dt, end=end_dt))
            index += 1
    return slots


def _teacher_available(teacher: Teacher, slot: Slot, duration_hours: int) -> bool:
    weekday = slot.start.weekday()
    desired_end = slot.start + timedelta(hours=duration_hours)
    if desired_end.date() != slot.start.date():
        return False
    has_availability = any(
        a.weekday == weekday
        and a.start_time <= slot.start.time()
        and a.end_time >= desired_end.time()
        for a in teacher.availabilities
    )
    if not has_availability:
        return False
    if any(un.date == slot.start.date() for un in teacher.unavailabilities):
        return False
    for session in teacher.sessions:
        if _overlap(session.start, session.end, slot.start, desired_end):
            return False
    return True


def _room_available(room: Room, slot: Slot, duration_hours: int) -> bool:
    desired_end = slot.start + timedelta(hours=duration_hours)
    if desired_end.date() != slot.start.date():
        return False
    for session in room.sessions:
        if _overlap(session.start, session.end, slot.start, desired_end):
            return False
    return True


def _overlap(start_a: datetime, end_a: datetime, start_b: datetime, end_b: datetime) -> bool:
    return start_a < end_b and start_b < end_a


class PlanningError(RuntimeError):
    """Raised when a schedule cannot be generated."""


def plan_sessions(start_day: date | None = None, days: int = 5) -> int:
    """Generate sessions for courses that still require planning.

    Returns the number of sessions created.
    """

    slots = generate_slots(start_day, days)
    courses = Course.query.all()
    teachers = Teacher.query.all()
    rooms = Room.query.all()

    tasks: list[tuple[Course, int]] = []
    for course in courses:
        remaining = max(course.session_count - len(course.sessions), 0)
        for i in range(remaining):
            tasks.append((course, i))

    if not tasks:
        return 0

    model = cp_model.CpModel()
    variables: dict[tuple[int, int, int, int], cp_model.IntVar] = {}

    for task_index, (course, _) in enumerate(tasks):
        for teacher in teachers:
            if teacher.max_hours_per_week <= 0:
                continue
            for room in rooms:
                if room.capacity < course.required_capacity:
                    continue
                if course.requires_computers and room.computers <= 0:
                    continue
                if course.materials:
                    course_material_ids = {m.id for m in course.materials}
                    room_material_ids = {m.id for m in room.materials}
                    if not course_material_ids.issubset(room_material_ids):
                        continue
                for slot in slots:
                    if not _teacher_available(teacher, slot, course.duration_hours):
                        continue
                    if not _room_available(room, slot, course.duration_hours):
                        continue
                    desired_end = slot.start + timedelta(hours=course.duration_hours)
                    if desired_end.time() > time(18, 0):
                        continue
                    var = model.NewBoolVar(
                        f"task_{task_index}_teacher_{teacher.id}_room_{room.id}_slot_{slot.index}"
                    )
                    variables[(task_index, teacher.id, room.id, slot.index)] = var

    if not variables:
        raise PlanningError("Aucune combinaison de créneaux n'est disponible pour planifier les cours.")

    for task_index, _ in enumerate(tasks):
        model.Add(sum(var for (t_idx, *_), var in variables.items() if t_idx == task_index) == 1)

    teacher_slot_usage: defaultdict[tuple[int, int], list[cp_model.IntVar]] = defaultdict(list)
    room_slot_usage: defaultdict[tuple[int, int], list[cp_model.IntVar]] = defaultdict(list)
    teacher_load: defaultdict[int, list[tuple[cp_model.IntVar, int]]] = defaultdict(list)

    for (task_index, teacher_id, room_id, slot_index), var in variables.items():
        teacher_slot_usage[(teacher_id, slot_index)].append(var)
        room_slot_usage[(room_id, slot_index)].append(var)
        teacher_load[teacher_id].append((var, tasks[task_index][0].duration_hours))

    for vars_ in teacher_slot_usage.values():
        model.Add(sum(vars_) <= 1)
    for vars_ in room_slot_usage.values():
        model.Add(sum(vars_) <= 1)

    for teacher in teachers:
        loads = teacher_load.get(teacher.id, [])
        if loads:
            model.Add(sum(var * duration for var, duration in loads) <= teacher.max_hours_per_week)

    model.Maximize(
        sum(
            var * tasks[task_index][0].priority
            for (task_index, _, _, _), var in variables.items()
        )
    )

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 10
    solver.parameters.num_search_workers = 8

    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise PlanningError("Impossible de générer un planning optimal.")

    created = 0
    for (task_index, teacher_id, room_id, slot_index), var in variables.items():
        if solver.Value(var):
            course, _ = tasks[task_index]
            slot = slots[slot_index]
            session = CourseSession(
                course_id=course.id,
                teacher_id=teacher_id,
                room_id=room_id,
                start=slot.start,
                end=slot.start + timedelta(hours=course.duration_hours),
            )
            db.session.add(session)
            created += 1

    db.session.commit()
    return created
