from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable

from ortools.sat.python import cp_model

from .extensions import db
from .models import Course, Room, Teacher

WORKING_HOURS = list(range(8, 18))
# Hours that cannot start a course due to breaks.
BLOCKED_HOURS = {10, 12, 13, 15}
DAYS = [0, 1, 2, 3, 4]  # Monday - Friday


@dataclass
class ScheduledCourse:
    course: Course
    start: datetime
    end: datetime


def generate_timeslots() -> list[tuple[int, int]]:
    slots: list[tuple[int, int]] = []
    for day in DAYS:
        for hour in WORKING_HOURS:
            if hour >= 18:
                continue
            if hour in BLOCKED_HOURS:
                continue
            slots.append((day, hour))
    return slots


TIMESLOTS = generate_timeslots()


def optimize_schedule(courses: Iterable[Course]) -> list[ScheduledCourse]:
    model = cp_model.CpModel()
    course_vars: dict[int, cp_model.IntVar] = {}

    timeslot_indices = list(range(len(TIMESLOTS)))
    for course in courses:
        course_vars[course.id] = model.NewIntVar(0, len(TIMESLOTS) - 1, f"course_{course.id}_slot")

    teacher_courses: dict[int, list[int]] = {}
    room_courses: dict[int, list[int]] = {}

    for course in courses:
        teacher_courses.setdefault(course.teacher_id, []).append(course.id)
        if course.room_id:
            room_courses.setdefault(course.room_id, []).append(course.id)

    def no_overlap(course_ids: list[int]) -> None:
        for i in range(len(course_ids)):
            for j in range(i + 1, len(course_ids)):
                ci = course_vars[course_ids[i]]
                cj = course_vars[course_ids[j]]
                model.Add(ci != cj)

    for ids in teacher_courses.values():
        no_overlap(ids)
    for ids in room_courses.values():
        no_overlap(ids)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5
    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RuntimeError("Impossible de générer un planning valide")

    scheduled: list[ScheduledCourse] = []
    for course in courses:
        index = solver.Value(course_vars[course.id])
        day, hour = TIMESLOTS[index]
        start = datetime.combine(course.start_time.date(), datetime.min.time()) + timedelta(days=day)
        start = start.replace(hour=hour, minute=0)
        end = start + timedelta(hours=course.duration_hours)
        scheduled.append(ScheduledCourse(course=course, start=start, end=end))

    return scheduled


def apply_schedule() -> list[ScheduledCourse]:
    courses = Course.query.order_by(Course.priority.desc()).all()
    scheduled = optimize_schedule(courses)
    for item in scheduled:
        item.course.start_time = item.start
        item.course.end_time = item.end
    db.session.commit()
    return scheduled
