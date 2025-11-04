from datetime import datetime, timedelta

import pytest

cp_model = pytest.importorskip("ortools.sat.python.cp_model")

from chronos.solver.incremental import build_incremental_model, solve_model


def _base_params():
    return {
        "day0": datetime(2024, 1, 1, 0, 0, 0),
        "freeze_room": False,
        "soft_lock_penalty": 10,
        "slot_minutes": 30,
    }


def test_td_precedes_tp_for_same_group():
    params = _base_params()

    new_sessions = [
        {
            "id": "td",
            "teacher_id": 1,
            "group_id": 1,
            "duration_slots": 2,
            "start_min_slot": 0,
            "start_max_slot": 10,
            "course_type": "TD",
            "chronology_key": ("course-id", 1, "S1"),
        },
        {
            "id": "tp",
            "teacher_id": 1,
            "group_id": 1,
            "duration_slots": 2,
            "start_min_slot": 0,
            "start_max_slot": 10,
            "course_type": "TP",
            "chronology_key": ("course-id", 1, "S1"),
        },
    ]

    model = build_incremental_model([], new_sessions, params)
    solver, status = solve_model(model, time_limit_s=5, workers=1, seed=123)

    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    td_start = solver.Value(new_sessions[0]["variables"]["start"])
    tp_start = solver.Value(new_sessions[1]["variables"]["start"])
    assert td_start <= tp_start


def test_td_precedes_sae_across_groups():
    params = _base_params()

    new_sessions = [
        {
            "id": "td",
            "teacher_id": 1,
            "group_id": 1,
            "duration_slots": 2,
            "start_min_slot": 0,
            "start_max_slot": 10,
            "course_type": "TD",
            "chronology_key": ("course-id", 1, "S1"),
        },
        {
            "id": "sae",
            "teacher_id": 2,
            "group_id": 2,
            "duration_slots": 2,
            "start_min_slot": 0,
            "start_max_slot": 10,
            "course_type": "SAE",
            "chronology_key": ("course-id", 1, "S1"),
        },
    ]

    model = build_incremental_model([], new_sessions, params)
    solver, status = solve_model(model, time_limit_s=5, workers=1, seed=123)

    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    td_start = solver.Value(new_sessions[0]["variables"]["start"])
    sae_start = solver.Value(new_sessions[1]["variables"]["start"])
    assert td_start <= sae_start


def test_locked_tp_forces_td_before_it():
    params = _base_params()
    day0 = params["day0"]

    locked_sessions = [
        {
            "start_dt": day0 + timedelta(hours=8),
            "end_dt": day0 + timedelta(hours=10),
            "teacher_id": 1,
            "group_id": 1,
            "room_id": 1,
            "course_type": "TP",
            "chronology_key": ("course-id", 1, "S1"),
        }
    ]

    new_sessions = [
        {
            "id": "td",
            "teacher_id": 1,
            "group_id": 1,
            "duration_slots": 2,
            "start_min_slot": 0,
            "start_max_slot": 10,
            "course_type": "TD",
            "chronology_key": ("course-id", 1, "S1"),
        }
    ]

    model = build_incremental_model(locked_sessions, new_sessions, params)
    solver, status = solve_model(model, time_limit_s=5, workers=1, seed=123)

    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    td_start = solver.Value(new_sessions[0]["variables"]["start"])
    assert td_start <= 16  # locked TP starts at slot 16 (8 hours / 0.5h per slot)

