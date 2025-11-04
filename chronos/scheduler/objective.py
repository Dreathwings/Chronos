"""Objective construction for the Chronos scheduler."""
from __future__ import annotations

from typing import List

from ortools.sat.python import cp_model

from .builder import SchedulerModel
from .config import SchedulerConfig


def apply_objective(scheduler_model: SchedulerModel, config: SchedulerConfig) -> None:
    """Attach a linear objective to the CP-SAT model."""

    model = scheduler_model.model
    weights = config.weights
    objective_terms: List[cp_model.LinearExpr] = []

    teacher_slot_usage = scheduler_model.variables.get("teacher_slot_usage", {})
    for teacher_slots in teacher_slot_usage.values():
        for slot_id, usage_var in teacher_slots.items():
            slot = scheduler_model.time_slots[slot_id]
            if slot.start.hour < 9:
                objective_terms.append(weights.early_slot_penalty * usage_var)
            if slot.end.hour >= 17:
                objective_terms.append(weights.late_slot_penalty * usage_var)

    for session in scheduler_model.sessions:
        options = scheduler_model.session_options[session.session_id]
        option_vars = scheduler_model.variables["session_option"][session.session_id]
        for teacher_id, assign_var in scheduler_model.variables["session_teacher"][session.session_id].items():
            teacher = scheduler_model.teachers[teacher_id]
            for option in options:
                if not teacher.disliked_slots.intersection(option.slot_ids):
                    continue
                penalty_var = model.NewBoolVar(
                    f"pref_penalty[{session.session_id},{teacher_id},{option.option_id}]"
                )
                model.Add(penalty_var <= assign_var)
                model.Add(penalty_var <= option_vars[option.option_id])
                model.Add(penalty_var >= assign_var + option_vars[option.option_id] - 1)
                objective_terms.append(weights.preference_miss_penalty * penalty_var)

    if objective_terms:
        model.Minimize(sum(objective_terms))
    else:
        model.Minimize(0)
