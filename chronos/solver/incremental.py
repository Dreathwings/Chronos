"""Incremental scheduling model builder for Chronos."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from math import ceil
from typing import Any, Iterable, Mapping, MutableMapping

COURSE_TYPE_PRIORITY: dict[str, int] = {
    "TD": 0,
    "TP": 1,
    "SAE": 1,
}


def _course_type_priority(course_type: Any) -> int | None:
    if not course_type:
        return None
    return COURSE_TYPE_PRIORITY.get(str(course_type).upper())


def _normalise_chronology_key(key: Any) -> tuple[Any, ...] | None:
    if key is None:
        return None
    if isinstance(key, tuple):
        return key
    if isinstance(key, list):
        return tuple(key)
    return (key,)


def to_slots(
    dt_start: datetime,
    dt_end: datetime,
    day0: datetime,
    slot_minutes: int,
) -> tuple[int, int]:
    """Convert a datetime range to discrete slot indices."""

    if slot_minutes <= 0:
        raise ValueError("slot_minutes must be a positive integer")
    if dt_end <= dt_start:
        raise ValueError("dt_end must be greater than dt_start")

    delta_start = dt_start - day0
    if delta_start.total_seconds() < 0:
        raise ValueError("dt_start must not be before day0")

    slot_size = slot_minutes * 60
    start_slot = int(delta_start.total_seconds() // slot_size)
    duration_seconds = (dt_end - dt_start).total_seconds()
    duration_slots = int(ceil(duration_seconds / slot_size))
    duration_slots = max(duration_slots, 1)
    end_slot = start_slot + duration_slots
    return start_slot, end_slot


def from_slot(slot_index: int, day0: datetime, slot_minutes: int) -> datetime:
    """Convert a discrete slot index back to a datetime."""

    if slot_minutes <= 0:
        raise ValueError("slot_minutes must be a positive integer")
    return day0 + timedelta(minutes=slot_minutes * slot_index)


def build_incremental_model(
    locked_sessions: Iterable[Mapping[str, Any]],
    new_sessions: Iterable[MutableMapping[str, Any]],
    params: Mapping[str, Any],
) -> cp_model.CpModel:
    """Build a CP-SAT model for incremental schedule generation."""

    from ortools.sat.python import cp_model

    model = cp_model.CpModel()
    slot_minutes = int(params.get("slot_minutes", 30))
    day0 = params.get("day0")
    if not isinstance(day0, datetime):
        raise ValueError("params['day0'] must be a datetime instance")
    freeze_room = bool(params.get("freeze_room", True))
    soft_lock_penalty = int(params.get("soft_lock_penalty", 0))

    teacher_intervals: defaultdict[int, list[cp_model.IntervalVar]] = defaultdict(list)
    group_intervals: defaultdict[int, list[cp_model.IntervalVar]] = defaultdict(list)
    room_intervals: defaultdict[int, list[cp_model.IntervalVar]] = defaultdict(list)
    objective_terms: list[cp_model.LinearExpr] = []
    chronology_buckets: defaultdict[
        tuple[int, tuple[Any, ...]], list[dict[str, Any]]
    ] = defaultdict(list)

    # Register locked sessions as immutable intervals.
    for index, session in enumerate(locked_sessions):
        start_dt = session.get("start_dt")
        end_dt = session.get("end_dt")
        teacher_id = session.get("teacher_id")
        group_id = session.get("group_id")
        room_id = session.get("room_id")
        if not isinstance(start_dt, datetime) or not isinstance(end_dt, datetime):
            raise ValueError("Locked sessions must include start_dt and end_dt datetimes")
        if teacher_id is None or group_id is None:
            raise ValueError("Locked sessions must include teacher_id and group_id")

        start_slot, end_slot = to_slots(start_dt, end_dt, day0, slot_minutes)
        duration = end_slot - start_slot
        start_var = model.NewConstant(start_slot)
        interval = model.NewFixedSizeIntervalVar(
            start_var, duration, f"locked_{index}"
        )
        teacher_intervals[int(teacher_id)].append(interval)
        group_intervals[int(group_id)].append(interval)
        if freeze_room and room_id is not None:
            room_intervals[int(room_id)].append(interval)

        chronology_key = _normalise_chronology_key(session.get("chronology_key"))
        priority = _course_type_priority(session.get("course_type"))
        if chronology_key is not None and priority is not None:
            bucket_key = (int(group_id), chronology_key)
            chronology_buckets[bucket_key].append(
                {"priority": priority, "start": start_var}
            )

    # Create variables for sessions to be scheduled.
    for index, session in enumerate(new_sessions):
        session_id = session.get("id", f"session_{index}")
        duration_slots = int(session.get("duration_slots", 0))
        if duration_slots <= 0:
            raise ValueError("Each new session must define a positive duration_slots")
        start_min = int(session.get("start_min_slot", 0))
        start_max = int(session.get("start_max_slot", start_min))
        if start_max < start_min:
            raise ValueError("start_max_slot must be >= start_min_slot")

        start_var = model.NewIntVar(start_min, start_max, f"start_{session_id}")
        end_var = model.NewIntVar(
            start_min + duration_slots, start_max + duration_slots, f"end_{session_id}"
        )
        interval = model.NewIntervalVar(
            start_var, duration_slots, end_var, f"interval_{session_id}"
        )
        session.setdefault("variables", {})
        session_vars: MutableMapping[str, Any] = session["variables"]
        session_vars.update({"start": start_var, "end": end_var, "interval": interval})

        teacher_id = session.get("teacher_id")
        group_id = session.get("group_id")
        if teacher_id is not None:
            teacher_intervals[int(teacher_id)].append(interval)
        if group_id is not None:
            group_intervals[int(group_id)].append(interval)

        candidate_rooms = session.get("room_candidates")
        room_literals: dict[int, cp_model.BoolVar] = {}
        room_var: cp_model.IntVar | None = None
        if candidate_rooms:
            candidate_ids = sorted({int(room_id) for room_id in candidate_rooms})
            if len(candidate_ids) == 1:
                assigned_room = candidate_ids[0]
                room_intervals[assigned_room].append(interval)
                session_vars["assigned_room"] = assigned_room
            else:
                domain = cp_model.Domain.FromValues(candidate_ids)
                room_var = model.NewIntVarFromDomain(domain, f"room_{session_id}")
                session_vars["room_var"] = room_var
                literals: list[cp_model.BoolVar] = []
                for candidate in candidate_ids:
                    literal = model.NewBoolVar(f"room_{session_id}_{candidate}")
                    model.Add(room_var == candidate).OnlyEnforceIf(literal)
                    model.Add(room_var != candidate).OnlyEnforceIf(literal.Not())
                    opt_interval = model.NewOptionalIntervalVar(
                        start_var,
                        duration_slots,
                        end_var,
                        literal,
                        f"interval_{session_id}_room_{candidate}",
                    )
                    room_intervals[candidate].append(opt_interval)
                    room_literals[candidate] = literal
                    literals.append(literal)
                model.AddExactlyOne(literals)
                session_vars["room_literals"] = room_literals
        else:
            assigned_room = session.get("room_id")
            if assigned_room is not None:
                room_intervals[int(assigned_room)].append(interval)
                session_vars["assigned_room"] = int(assigned_room)

        soft_lock = session.get("soft_lock") or {}
        if "start_slot" in soft_lock:
            keep_time = model.NewBoolVar(f"keep_time_{session_id}")
            model.Add(start_var == int(soft_lock["start_slot"])).OnlyEnforceIf(keep_time)
            session_vars["keep_time"] = keep_time
            penalty_value = int(soft_lock.get("penalty", soft_lock_penalty))
            if penalty_value:
                objective_terms.append(penalty_value * (1 - keep_time))
        if "room_id" in soft_lock:
            keep_room = model.NewBoolVar(f"keep_room_{session_id}")
            target_room = int(soft_lock["room_id"])
            session_vars["keep_room"] = keep_room
            penalty_value = int(soft_lock.get("room_penalty", soft_lock_penalty))
            if room_var is not None:
                model.Add(room_var == target_room).OnlyEnforceIf(keep_room)
            elif target_room == session_vars.get("assigned_room"):
                model.Add(keep_room == 1)
            if room_literals and target_room in room_literals:
                model.Add(room_literals[target_room]).OnlyEnforceIf(keep_room)
            if penalty_value:
                objective_terms.append(penalty_value * (1 - keep_room))

        chronology_key = _normalise_chronology_key(session.get("chronology_key"))
        priority = _course_type_priority(session.get("course_type"))
        if (
            chronology_key is not None
            and priority is not None
            and group_id is not None
        ):
            bucket_key = (int(group_id), chronology_key)
            chronology_buckets[bucket_key].append(
                {"priority": priority, "start": start_var}
            )

    for teacher_id, intervals in teacher_intervals.items():
        if len(intervals) > 1:
            model.AddNoOverlap(intervals)
    for group_id, intervals in group_intervals.items():
        if len(intervals) > 1:
            model.AddNoOverlap(intervals)
    for room_id, intervals in room_intervals.items():
        if len(intervals) > 1:
            model.AddNoOverlap(intervals)

    for entries in chronology_buckets.values():
        if len(entries) < 2:
            continue
        sorted_entries = sorted(entries, key=lambda item: item["priority"])
        for idx, earlier in enumerate(sorted_entries):
            for later in sorted_entries[idx + 1 :]:
                if earlier["priority"] < later["priority"]:
                    model.Add(earlier["start"] <= later["start"])

    if objective_terms:
        model.Minimize(cp_model.LinearExpr.Sum(objective_terms))
    else:
        model.Minimize(0)

    return model


def solve_model(
    model: cp_model.CpModel,
    time_limit_s: int | float | None = None,
    workers: int | None = None,
    seed: int | None = None,
) -> tuple[cp_model.CpSolver, int]:
    """Solve the given model with CP-SAT."""

    from ortools.sat.python import cp_model

    solver = cp_model.CpSolver()
    if time_limit_s is not None:
        solver.parameters.max_time_in_seconds = float(time_limit_s)
    if workers is not None:
        solver.parameters.num_search_workers = int(workers)
    if seed is not None:
        solver.parameters.random_seed = int(seed)
    status = solver.Solve(model)
    return solver, status
