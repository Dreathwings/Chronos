"""Incremental planning solver for Chronos."""

from __future__ import annotations

import importlib
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Dict, Iterable, List, Mapping, MutableMapping, Sequence

if TYPE_CHECKING:  # pragma: no cover - only evaluated by type checkers
    from ortools.sat.python import cp_model


DEFAULT_SLOT_MINUTES = 30

_CP_MODEL: "cp_model" | None = None


def get_cp_model() -> "cp_model":
    """Load and cache the OR-Tools cp_model module."""

    global _CP_MODEL
    if _CP_MODEL is None:
        module = importlib.import_module("ortools.sat.python.cp_model")
        _CP_MODEL = module  # type: ignore[assignment]
    return _CP_MODEL  # type: ignore[return-value]


class IncrementalModelError(RuntimeError):
    """Raised when the incremental model cannot be constructed."""


def to_slots(
    dt_start: datetime,
    dt_end: datetime,
    day0: datetime,
    slot_minutes: int = DEFAULT_SLOT_MINUTES,
) -> tuple[int, int]:
    """Convert datetime bounds to discrete slot indices."""

    if slot_minutes <= 0:
        raise ValueError("slot_minutes must be a positive integer")

    delta_start = dt_start - day0
    delta_end = dt_end - day0
    slot_length = slot_minutes * 60
    start_slot = int(delta_start.total_seconds() // slot_length)
    end_slot = int(delta_end.total_seconds() // slot_length)
    return start_slot, end_slot


def from_slot(
    slot_index: int,
    day0: datetime,
    slot_minutes: int = DEFAULT_SLOT_MINUTES,
) -> datetime:
    """Convert a slot index back to a datetime."""

    if slot_minutes <= 0:
        raise ValueError("slot_minutes must be a positive integer")

    return day0 + timedelta(minutes=slot_index * slot_minutes)


def _extract_start_domain(session: Mapping[str, object]) -> "cp_model.Domain":
    cp_model = get_cp_model()
    domain_values: Sequence[int] | None = session.get("start_domain")  # type: ignore[assignment]
    if domain_values:
        return cp_model.Domain.FromValues(sorted(int(v) for v in domain_values))

    candidate_slots: Sequence[int] | None = session.get("candidate_start_slots")  # type: ignore[assignment]
    if candidate_slots:
        return cp_model.Domain.FromValues(sorted(int(v) for v in candidate_slots))

    start_min = session.get("start_min_slot")
    start_max = session.get("start_max_slot")
    if start_min is not None and start_max is not None:
        start_min = int(start_min)
        start_max = int(start_max)
        if start_min > start_max:
            start_min, start_max = start_max, start_min
        return cp_model.Domain.FromIntervals([(start_min, start_max)])

    start_slot = session.get("start_slot")
    if start_slot is not None:
        start_slot = int(start_slot)
        return cp_model.Domain.FromValues([start_slot])

    raise IncrementalModelError("Session is missing start domain information")


def _normalise_group_ids(raw_groups: object) -> List[int]:
    if raw_groups is None:
        return []
    if isinstance(raw_groups, (list, tuple, set)):
        return [int(group) for group in raw_groups]
    return [int(raw_groups)]


def build_incremental_model(
    locked_sessions: Sequence[Mapping[str, object]],
    new_sessions: MutableMapping[str, Mapping[str, object]] | Sequence[MutableMapping[str, object]],
    params: Mapping[str, object],
) -> "cp_model.CpModel":
    """Build the CP-SAT model for incremental planning."""

    day0 = params.get("day0")
    if not isinstance(day0, datetime):
        raise IncrementalModelError("params['day0'] must be a datetime instance")
    slot_minutes = int(params.get("slot_minutes", DEFAULT_SLOT_MINUTES))
    freeze_room = bool(params.get("freeze_room", True))
    soft_lock_penalty = int(params.get("soft_lock_penalty", 1000))

    cp_model = get_cp_model()

    model = cp_model.CpModel()

    teacher_intervals: Dict[int, List["cp_model.IntervalVar"]] = {}
    room_intervals: Dict[int, List["cp_model.IntervalVar"]] = {}
    group_intervals: Dict[int, List["cp_model.IntervalVar"]] = {}
    penalty_terms: List["cp_model.LinearExpr"] = []

    def _register_interval(
        mapping: Dict[int, List["cp_model.IntervalVar"]],
        key: int,
        interval: "cp_model.IntervalVar",
    ) -> None:
        mapping.setdefault(key, []).append(interval)

    for locked in locked_sessions:
        start_dt = locked.get("start_dt")
        end_dt = locked.get("end_dt")
        if not isinstance(start_dt, datetime) or not isinstance(end_dt, datetime):
            raise IncrementalModelError("Locked sessions must include datetime start_dt/end_dt")
        start_slot, end_slot = to_slots(start_dt, end_dt, day0, slot_minutes)
        duration = end_slot - start_slot
        if duration <= 0:
            raise IncrementalModelError("Locked session has non-positive duration")
        teacher_id = int(locked.get("teacher_id"))
        interval_name = f"locked_teacher_{teacher_id}_{start_slot}"
        teacher_interval = model.NewFixedSizeIntervalVar(start_slot, duration, interval_name)
        _register_interval(teacher_intervals, teacher_id, teacher_interval)

        group_id = locked.get("group_id")
        for gid in _normalise_group_ids(group_id):
            group_interval = model.NewFixedSizeIntervalVar(
                start_slot,
                duration,
                f"locked_group_{gid}_{start_slot}",
            )
            _register_interval(group_intervals, gid, group_interval)

        if freeze_room:
            room_id = locked.get("room_id")
            if room_id is not None:
                room_interval = model.NewFixedSizeIntervalVar(
                    start_slot,
                    duration,
                    f"locked_room_{room_id}_{start_slot}",
                )
                _register_interval(room_intervals, int(room_id), room_interval)

    sessions_iterable: Iterable[MutableMapping[str, object]]
    if isinstance(new_sessions, Mapping):
        sessions_iterable = list(new_sessions.values())
    else:
        sessions_iterable = list(new_sessions)

    for session in sessions_iterable:
        duration_slots = int(session.get("duration_slots", 0))
        if duration_slots <= 0:
            soft_lock = session.get("soft_lock") or {}
            start_slot = soft_lock.get("start_slot")
            end_slot = soft_lock.get("end_slot")
            if start_slot is not None and end_slot is not None:
                duration_slots = int(end_slot) - int(start_slot)
        if duration_slots <= 0:
            raise IncrementalModelError("Session is missing a positive duration")

        domain = _extract_start_domain(session)
        start_var = model.NewIntVarFromDomain(domain, f"start_{session.get('id', 'session')}")
        end_var = model.NewIntVar(0, 10**6, f"end_{session.get('id', 'session')}")
        model.Add(end_var == start_var + duration_slots)
        interval = model.NewIntervalVar(start_var, duration_slots, end_var, f"interval_{session.get('id', 'session')}")

        cp_info: Dict[str, object] = {
            "start": start_var,
            "end": end_var,
            "interval": interval,
            "duration": duration_slots,
        }

        teacher_id = session.get("teacher_id")
        if teacher_id is None:
            raise IncrementalModelError("Session is missing teacher_id")
        teacher_id = int(teacher_id)
        _register_interval(teacher_intervals, teacher_id, interval)

        for gid in _normalise_group_ids(session.get("group_ids") or session.get("group_id")):
            _register_interval(group_intervals, gid, interval)

        room_ids: Sequence[int] | None = session.get("room_ids")  # type: ignore[assignment]
        if room_ids is None and session.get("room_id") is not None:
            room_ids = [int(session.get("room_id"))]

        room_literals: Dict[int, "cp_model.IntVar"] = {}
        if room_ids:
            room_ids = [int(rid) for rid in room_ids]
            if len(room_ids) == 1:
                chosen_room = room_ids[0]
                room_interval = model.NewIntervalVar(
                    start_var,
                    duration_slots,
                    end_var,
                    f"room_{chosen_room}_{session.get('id', 'session')}",
                )
                _register_interval(room_intervals, chosen_room, room_interval)
                cp_info["room_interval"] = {chosen_room: room_interval}
            else:
                room_choice = model.NewIntVarFromDomain(
                    cp_model.Domain.FromValues(room_ids),
                    f"room_choice_{session.get('id', 'session')}",
                )
                cp_info["room_choice"] = room_choice
                literals: List["cp_model.IntVar"] = []
                room_interval_map: Dict[int, "cp_model.IntervalVar"] = {}
                for rid in room_ids:
                    lit = model.NewBoolVar(f"use_room_{rid}_{session.get('id', 'session')}")
                    literals.append(lit)
                    room_literals[rid] = lit
                    opt_interval = model.NewOptionalIntervalVar(
                        start_var,
                        duration_slots,
                        end_var,
                        lit,
                        f"room_{rid}_{session.get('id', 'session')}",
                    )
                    room_interval_map[rid] = opt_interval
                    _register_interval(room_intervals, rid, opt_interval)
                    model.Add(room_choice == rid).OnlyEnforceIf(lit)
                    model.Add(room_choice != rid).OnlyEnforceIf(lit.Not())
                model.Add(sum(literals) == 1)
                cp_info["room_interval"] = room_interval_map
                cp_info["room_literals"] = room_literals
        session["_cp_vars"] = cp_info

        soft_lock = session.get("soft_lock") or {}
        if soft_lock:
            penalty_weight = soft_lock.get("penalty", soft_lock_penalty)
            keep_time = model.NewBoolVar(f"keep_time_{session.get('id', 'session')}")
            break_time = model.NewBoolVar(f"break_time_{session.get('id', 'session')}")
            model.Add(keep_time + break_time == 1)
            if "start_slot" in soft_lock:
                locked_start = int(soft_lock["start_slot"])
                model.Add(start_var == locked_start).OnlyEnforceIf(keep_time)
                model.Add(start_var != locked_start).OnlyEnforceIf(break_time)
            else:
                model.Add(keep_time == 0)
                model.Add(break_time == 1)
            penalty_terms.append(penalty_weight * break_time)
            cp_info["keep_time"] = keep_time
            cp_info["break_time"] = break_time

            if "room_id" in soft_lock and room_literals:
                locked_room = int(soft_lock["room_id"])
                keep_room = model.NewBoolVar(f"keep_room_{session.get('id', 'session')}")
                break_room = model.NewBoolVar(f"break_room_{session.get('id', 'session')}")
                model.Add(keep_room + break_room == 1)
                lit = room_literals.get(locked_room)
                if lit is not None:
                    model.Add(lit == 1).OnlyEnforceIf(keep_room)
                    model.Add(lit == 0).OnlyEnforceIf(break_room)
                else:
                    model.Add(keep_room == 0)
                    model.Add(break_room == 1)
                penalty_terms.append(penalty_weight * break_room)
                cp_info["keep_room"] = keep_room
                cp_info["break_room"] = break_room

    for teacher_id, intervals in teacher_intervals.items():
        if len(intervals) > 1:
            model.AddNoOverlap(intervals)

    for group_id, intervals in group_intervals.items():
        if len(intervals) > 1:
            model.AddNoOverlap(intervals)

    if freeze_room:
        for room_id, intervals in room_intervals.items():
            if len(intervals) > 1:
                model.AddNoOverlap(intervals)

    if penalty_terms:
        model.Minimize(sum(penalty_terms))
    else:
        model.Minimize(0)

    return model


def solve_model(
    model: "cp_model.CpModel",
    time_limit_s: float | int | None = None,
    workers: int | None = None,
    seed: int | None = None,
) -> tuple["cp_model.CpSolver", "cp_model.OptStatus"]:
    """Solve the provided model with CP-SAT."""

    cp_model = get_cp_model()

    solver = cp_model.CpSolver()
    if time_limit_s is not None:
        solver.parameters.max_time_in_seconds = float(time_limit_s)
    if workers is not None:
        solver.parameters.num_search_workers = int(workers)
    if seed is not None:
        solver.parameters.random_seed = int(seed)
    status = solver.Solve(model)
    return solver, status


__all__ = [
    "build_incremental_model",
    "solve_model",
    "to_slots",
    "from_slot",
    "get_cp_model",
]
