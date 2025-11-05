import json
import json
from pathlib import Path

import pytest

from chronos.scheduler.api import generate_schedule
from chronos.scheduler.builder import build_model
from chronos.scheduler.config import DEFAULT_CONFIG
from chronos.scheduler.validate import validate_input

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def load_example(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text())


def test_small_schedule_valid(tmp_path):
    data = load_example("input_small.json")
    result = generate_schedule(data)
    sessions = result["sessions"]
    assert len(sessions) == 2

    cm_session = next(session for session in sessions if session["course_id"] == "C1")
    td_session = next(session for session in sessions if session["course_id"] == "C2")

    assert cm_session["teacher_id"] == "T1"
    assert td_session["teacher_id"] == "T2"
    assert cm_session["room_id"] == "R1"

    cm_start = (cm_session["date"], cm_session["start"])
    td_start = (td_session["date"], td_session["start"])
    assert cm_start < td_start

    lunch_hours = {"12:00", "13:00"}
    for session in sessions:
        assert session["start"] not in lunch_hours


def test_room_capacity_validation():
    data = load_example("input_small.json")
    data["rooms"] = [
        {"room_id": "Rtiny", "name": "Small", "capacity": 10, "equipment": ["projector"]}
    ]
    validated = validate_input(data)
    with pytest.raises(ValueError):
        build_model(validated, DEFAULT_CONFIG)


def test_session_priority_uses_availability_intersection():
    data = load_example("input_small.json")
    validated = validate_input(data)
    model = build_model(validated, DEFAULT_CONFIG)

    assert model.session_priority == ["C2#0", "C1#0"]
    assert model.session_options["C2#0"][0].slot_ids != model.session_options["C1#0"][0].slot_ids

def test_medium_schedule_all_sessions():
    data = load_example("input_medium.json")
    result = generate_schedule(data)
    sessions = result["sessions"]
    expected = sum(course["total_units"] * len(course["groups"]) for course in data["courses"])
    assert len(sessions) == expected
    # Verify precedence: each TD happens after the CM on its module
    cm_sessions = {
        session["course_id"]: (session["date"], session["start"])
        for session in sessions
        if session["course_id"] in {"C1", "C4"}
    }
    for session in sessions:
        if session["course_id"] in {"C2", "C3", "C5"}:
            prereq = "C1" if session["course_id"] in {"C2", "C3"} else "C4"
            assert (session["date"], session["start"]) > cm_sessions[prereq]

    # Verify incompatible groups never overlap
    grouped_sessions = {}
    for session in sessions:
        key = (session["date"], session["start"])
        grouped_sessions.setdefault(key, []).append(session)
    for key, occurrences in grouped_sessions.items():
        involved_groups = {item["group_id"] for item in occurrences}
        if {"G1", "G2"}.issubset(involved_groups):
            course_ids = {item["course_id"] for item in occurrences}
            # Compatible only if the shared slot is the same course (joint lecture)
            assert len(course_ids) == 1
