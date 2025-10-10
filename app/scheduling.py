from __future__ import annotations

from dataclasses import dataclass
from datetime import time, timedelta
from typing import Iterable, Sequence

from ortools.sat.python import cp_model
from sqlalchemy.orm import joinedload

from .models import Course, CourseSession, Room, Teacher
from .extensions import db


DAYS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi"]
SLOTS: list[time] = [
    time(8, 0),
    time(9, 0),
    time(10, 15),
    time(11, 15),
    time(13, 15),
    time(14, 15),
    time(15, 30),
    time(16, 30),
]
SLOT_DURATION = timedelta(hours=1)
SLOT_MINUTES = [slot.hour * 60 + slot.minute for slot in SLOTS]


@dataclass
class ScheduledSession:
    course: Course
    teacher: Teacher
    room: Room
    day_index: int
    start_slot: int
    duration_slots: int

    @property
    def start_time(self) -> time:
        return SLOTS[self.start_slot]

    @property
    def end_time(self) -> time:
        end_slot = self.start_slot + self.duration_slots
        base_time = SLOTS[self.start_slot]
        total_minutes = base_time.hour * 60 + base_time.minute
        total_minutes += int(SLOT_DURATION.total_seconds() // 60) * self.duration_slots
        return time(total_minutes // 60, total_minutes % 60)

    @property
    def day_name(self) -> str:
        return DAYS[self.day_index]


class SchedulingError(RuntimeError):
    """Raised when the CP-SAT solver fails to build a plan."""


class ScheduleBuilder:
    """High level API orchestrating the CP-SAT optimisation model."""

    def __init__(self, courses: Sequence[Course]):
        self.courses = [c for c in courses if c.teacher and c.room]
        self.model = cp_model.CpModel()
        self.horizon = len(DAYS) * len(SLOTS)
        self.variables: dict[int, tuple[cp_model.IntVar, cp_model.IntervalVar, int]] = {}
        self.unplanned_courses: list[Course] = []

    def build(self) -> list[ScheduledSession]:
        if not self.courses:
            return []

        self._create_variables()
        self._add_teacher_constraints()
        self._add_room_constraints()
        self._add_soft_objective()

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 10
        solver.parameters.num_search_workers = 8

        status = solver.Solve(self.model)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            raise SchedulingError("Impossible de générer un créneau pour les cours existants")

        sessions: list[ScheduledSession] = []
        for course in self.courses:
            start_var, interval_var, duration = self.variables[course.id]
            start_value = solver.Value(start_var)
            day_index = start_value // len(SLOTS)
            start_slot = start_value % len(SLOTS)
            sessions.append(
                ScheduledSession(
                    course=course,
                    teacher=course.teacher,
                    room=course.room,
                    day_index=day_index,
                    start_slot=start_slot,
                    duration_slots=duration,
                )
            )
        return sessions

    def _create_variables(self) -> None:
        total_slots = len(SLOTS)
        valid_courses: list[Course] = []
        for course in self.courses:
            duration_slots = max(1, course.duration_hours)
            valid_starts: list[int] = []
            for day_index in range(len(DAYS)):
                for slot_index in range(total_slots - duration_slots + 1):
                    if duration_slots > 1:
                        contiguous = True
                        for offset in range(1, duration_slots):
                            prev_minutes = SLOT_MINUTES[slot_index + offset - 1]
                            current_minutes = SLOT_MINUTES[slot_index + offset]
                            if current_minutes - prev_minutes != 60:
                                contiguous = False
                                break
                        if not contiguous:
                            continue
                    valid_starts.append(day_index * total_slots + slot_index)
            if not valid_starts:
                self.unplanned_courses.append(course)
                continue
            start_var = self.model.NewIntVarFromDomain(
                cp_model.Domain.FromValues(valid_starts), f"start_{course.id}"
            )
            end_var = self.model.NewIntVar(0, self.horizon, f"end_{course.id}")
            self.model.Add(end_var == start_var + duration_slots)
            interval = self.model.NewIntervalVar(
                start_var, duration_slots, end_var, f"interval_{course.id}"
            )
            self.variables[course.id] = (start_var, interval, duration_slots)
            valid_courses.append(course)
        self.courses = valid_courses
        if self.unplanned_courses:
            course_names = ", ".join(course.title for course in self.unplanned_courses)
            raise SchedulingError(
                f"Impossible de placer les cours suivants dans les créneaux disponibles : {course_names}."
            )

    def _add_teacher_constraints(self) -> None:
        for teacher in {course.teacher for course in self.courses if course.teacher}:
            intervals = [self.variables[course.id][1] for course in self.courses if course.teacher == teacher]
            if len(intervals) > 1:
                self.model.AddNoOverlap(intervals)

    def _add_room_constraints(self) -> None:
        for room in {course.room for course in self.courses if course.room}:
            intervals = [self.variables[course.id][1] for course in self.courses if course.room == room]
            if len(intervals) > 1:
                self.model.AddNoOverlap(intervals)

    def _add_soft_objective(self) -> None:
        if not self.variables:
            return
        objective_terms = []
        total_slots = len(SLOTS)
        for course in self.courses:
            start_var, _interval, _duration = self.variables[course.id]
            weight = max(1, 10 - course.priority)
            objective_terms.append(start_var * weight)
            # Encourage courses happening before their end_date if provided
            if course.start_date and course.end_date:
                total_days = (course.end_date - course.start_date).days + 1
                if total_days > 0:
                    latest_day = min(len(DAYS) - 1, total_days - 1)
                    limit = (latest_day + 1) * total_slots
                    slack = self.model.NewIntVar(0, self.horizon, f"slack_{course.id}")
                    self.model.Add(slack >= start_var - limit)
                    objective_terms.append(slack)
        self.model.Minimize(sum(objective_terms))


def generate_schedule() -> list[CourseSession]:
    courses: list[Course] = Course.query.options(
        joinedload(Course.teacher),
        joinedload(Course.room),
    ).all()

    for course in courses:
        if course.room and course.room.capacity < course.group_size:
            raise SchedulingError(
                f"La salle {course.room.name} est trop petite pour {course.title}."
            )
        if course.room and course.required_equipments:
            required = {item.strip().lower() for item in course.required_equipments.split(",") if item.strip()}
            equipments = {
                item.strip().lower()
                for item in (course.room.equipments or "").split(",")
                if item.strip()
            }
            missing = required - equipments
            if missing:
                raise SchedulingError(
                    f"Équipements manquants dans {course.room.name}: {', '.join(sorted(missing))}."
                )

    builder = ScheduleBuilder(courses)
    sessions = builder.build()

    CourseSession.query.delete(synchronize_session=False)
    db.session.flush()

    instances: list[CourseSession] = []
    for session in sessions:
        instances.append(
            CourseSession(
                course=session.course,
                teacher=session.teacher,
                room=session.room,
                day_of_week=session.day_index,
                start_time=session.start_time,
                end_time=session.end_time,
            )
        )
    db.session.add_all(instances)
    db.session.commit()
    return instances


def group_sessions_by_day(sessions: Iterable[CourseSession]) -> dict[str, list[CourseSession]]:
    grouped: dict[str, list[CourseSession]] = {day: [] for day in DAYS}
    for session in sessions:
        day_name = DAYS[session.day_of_week]
        grouped.setdefault(day_name, []).append(session)
    for day_sessions in grouped.values():
        day_sessions.sort(key=lambda s: (s.start_time, s.course.title))
    return grouped
