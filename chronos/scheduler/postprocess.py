"""Post-processing utilities for the Chronos scheduler."""
from __future__ import annotations

from typing import Dict, List

from ortools.sat.python import cp_model

from .builder import SchedulerModel
from .model import ScheduleResult


def build_schedule_result(scheduler_model: SchedulerModel, solver: cp_model.CpSolver) -> ScheduleResult:
    """Reconstruct the scheduled sessions from the solver assignment."""

    sessions_output: List[Dict[str, object]] = []
    for session in scheduler_model.sessions:
        option_vars = scheduler_model.variables["session_option"][session.session_id]
        chosen_option = next(
            option
            for option in scheduler_model.session_options[session.session_id]
            if solver.Value(option_vars[option.option_id]) == 1
        )
        teacher_id = next(
            teacher_id
            for teacher_id, var in scheduler_model.variables["session_teacher"][session.session_id].items()
            if solver.Value(var) == 1
        )
        room_id = next(
            room_id
            for room_id, var in scheduler_model.variables["session_room"][session.session_id].items()
            if solver.Value(var) == 1
        )
        for group_id in session.groups:
            sessions_output.append(
                {
                    "session_id": session.session_id,
                    "course_id": session.course_id,
                    "type": session.type,
                    "teacher_id": teacher_id,
                    "group_id": group_id,
                    "room_id": room_id,
                    "date": chosen_option.day,
                    "start": chosen_option.start,
                    "end": chosen_option.end,
                }
            )

    metrics = {
        "objective_value": solver.ObjectiveValue(),
        "best_bound": solver.BestObjectiveBound(),
        "status": solver.StatusName(),
    }
    return ScheduleResult(sessions=sessions_output, metrics=metrics)
