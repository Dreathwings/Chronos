"""Constraint programming solver using OR-Tools."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, List

from ortools.sat.python import cp_model

from ..models import Assignment, Course, CourseRequirement, Room, Teacher, Timeslot


@dataclass
class AssignmentDecision:
    course: Course
    session_index: int
    timeslot: Timeslot
    room: Room


def solve_timetable(session) -> List[AssignmentDecision]:
    """Run the CP-SAT solver to produce a feasible timetable."""
    courses: list[Course] = session.query(Course).all()
    timeslots: list[Timeslot] = session.query(Timeslot).all()
    rooms: list[Room] = session.query(Room).all()

    if not courses:
        return []
    if not timeslots:
        raise ValueError("No timeslots available. Generate timeslots first.")
    if not rooms:
        raise ValueError("No rooms available.")

    model = cp_model.CpModel()

    assignment_vars: dict[tuple[int, int, int, int], cp_model.IntVar] = {}
    session_options: dict[tuple[int, int], list[tuple[int, int, int]]] = defaultdict(list)

    for course in courses:
        teacher = course.teacher
        for session_index in range(course.sessions_count):
            session_key = (course.id, session_index)
            for timeslot in timeslots:
                if timeslot.minutes != course.session_minutes:
                    continue
                if not (course.window_start <= timeslot.date <= course.window_end):
                    continue
                if not _teacher_available(teacher, timeslot):
                    continue
                for room in rooms:
                    if room.capacity < course.size:
                        continue
                    if not _room_supports_requirements(room, course.requirements):
                        continue
                    var = model.NewBoolVar(
                        f"c{course.id}_s{session_index}_t{timeslot.id}_r{room.id}"
                    )
                    key = (course.id, session_index, timeslot.id, room.id)
                    assignment_vars[key] = var
                    session_options[session_key].append(
                        (timeslot.id, room.id, course.teacher_id)
                    )
            if not session_options[session_key]:
                raise ValueError(
                    f"No feasible timeslot/room for course {course.name} session {session_index + 1}."
                )

    if not assignment_vars:
        raise ValueError("No feasible assignment options found. Check constraints.")

    # Each session must be assigned exactly once.
    for (course_id, session_index), options in session_options.items():
        vars_for_session = [
            assignment_vars[(course_id, session_index, timeslot_id, room_id)]
            for timeslot_id, room_id, _ in options
        ]
        model.Add(sum(vars_for_session) == 1)

    # Prevent overlapping assignments for rooms and teachers
    for timeslot in timeslots:
        room_assignments: dict[int, list[cp_model.IntVar]] = defaultdict(list)
        teacher_assignments: dict[int, list[cp_model.IntVar]] = defaultdict(list)
        for (course_id, session_index, timeslot_id, room_id), var in assignment_vars.items():
            if timeslot_id != timeslot.id:
                continue
            _, _, teacher_id = next(
                option
                for option in session_options[(course_id, session_index)]
                if option[0] == timeslot_id and option[1] == room_id
            )
            room_assignments[room_id].append(var)
            teacher_assignments[teacher_id].append(var)
        for vars_for_room in room_assignments.values():
            model.Add(sum(vars_for_room) <= 1)
        for vars_for_teacher in teacher_assignments.values():
            model.Add(sum(vars_for_teacher) <= 1)

    # Teacher workload constraints
    for teacher in session.query(Teacher).all():
        relevant_vars = []
        for (course_id, session_index, timeslot_id, room_id), var in assignment_vars.items():
            _, _, teacher_id = next(
                option
                for option in session_options[(course_id, session_index)]
                if option[0] == timeslot_id and option[1] == room_id
            )
            if teacher_id == teacher.id:
                course = next(c for c in courses if c.id == course_id)
                relevant_vars.append((var, course.session_minutes))
        if relevant_vars:
            model.Add(
                sum(var * minutes for var, minutes in relevant_vars)
                <= teacher.max_weekly_load_hrs * 60
            )

    # Simple objective: favour earlier timeslots and smaller rooms to leave capacity
    objective_terms = []
    for (course_id, session_index, timeslot_id, room_id), var in assignment_vars.items():
        objective_terms.append(var * (timeslot_id * 1000 + room_id))
    model.Minimize(sum(objective_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 10
    result = solver.Solve(model)
    if result not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise ValueError("No feasible timetable could be generated with current data.")

    decisions: list[AssignmentDecision] = []
    timeslot_map = {timeslot.id: timeslot for timeslot in timeslots}
    room_map = {room.id: room for room in rooms}
    course_map = {course.id: course for course in courses}

    for (course_id, session_index, timeslot_id, room_id), var in assignment_vars.items():
        if solver.Value(var):
            decisions.append(
                AssignmentDecision(
                    course=course_map[course_id],
                    session_index=session_index,
                    timeslot=timeslot_map[timeslot_id],
                    room=room_map[room_id],
                )
            )

    return decisions


def persist_assignments(session, decisions: Iterable[AssignmentDecision]) -> list[Assignment]:
    """Persist solver decisions to the database."""
    session.query(Assignment).delete(synchronize_session=False)
    created: list[Assignment] = []
    for decision in decisions:
        created.append(
            Assignment(
                course_id=decision.course.id,
                session_index=decision.session_index,
                timeslot_id=decision.timeslot.id,
                room_id=decision.room.id,
                teacher_id=decision.course.teacher_id,
                status="scheduled",
            )
        )
    session.add_all(created)
    session.commit()
    return created


def _teacher_available(teacher: Teacher, timeslot: Timeslot) -> bool:
    if teacher is None:
        return False

    weekday = timeslot.date.weekday()
    if teacher.availabilities:
        if not any(
            availability.weekday == weekday
            and availability.start_time <= timeslot.start_time
            and availability.end_time >= timeslot.end_time
            for availability in teacher.availabilities
        ):
            return False

    if any(
        unavailability.date == timeslot.date
        and unavailability.start_time <= timeslot.start_time
        and unavailability.end_time >= timeslot.end_time
        for unavailability in teacher.unavailabilities
    ):
        return False

    return True


def _room_supports_requirements(
    room: Room, requirements: Iterable[CourseRequirement]
) -> bool:
    equipment_lookup = {(equipment.key, equipment.value) for equipment in room.equipment}
    for requirement in requirements:
        if (requirement.key, requirement.value) not in equipment_lookup:
            return False
    return True
