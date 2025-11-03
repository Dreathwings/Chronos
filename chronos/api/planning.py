"""Planning API endpoints for Chronos."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, MutableMapping

from flask import current_app, jsonify, request
from ortools.sat.python import cp_model
from sqlalchemy import func
from werkzeug.exceptions import BadRequest, NotFound

from app import db
from chronos.api import bp
from chronos.models import PlanningVersion, SessionValidated
from chronos.solver.incremental import (
    build_incremental_model,
    from_slot,
    solve_model,
    to_slots,
)


STATUS_LABELS = {
    cp_model.OPTIMAL: "OPTIMAL",
    cp_model.FEASIBLE: "FEASIBLE",
    cp_model.INFEASIBLE: "INFEASIBLE",
    cp_model.MODEL_INVALID: "MODEL_INVALID",
    cp_model.UNKNOWN: "UNKNOWN",
}


def _parse_week_start(label: str) -> datetime:
    try:
        return datetime.strptime(f"{label}-1", "%G-W%V-%u")
    except ValueError as exc:  # pragma: no cover - guard for malformed inputs
        raise BadRequest(f"Invalid base_version '{label}': {exc}") from exc


def _serialise_session(session: SessionValidated) -> Dict[str, Any]:
    return {
        "id": session.id,
        "course_id": session.course_id,
        "teacher_id": session.teacher_id,
        "group_id": session.group_id,
        "room_id": session.room_id,
        "start": session.start_dt.isoformat(),
        "end": session.end_dt.isoformat(),
    }


@bp.route("/generate", methods=["POST"])
def generate_planning() -> Any:
    """Generate an incremental planning solution."""

    mode = request.args.get("mode")
    if mode != "incremental":
        raise BadRequest("Unsupported mode; only 'incremental' is available")

    base_version_label = request.args.get("base_version")
    if not base_version_label:
        raise BadRequest("Missing base_version query parameter")

    payload = request.get_json(silent=True) or {}

    freeze_room = bool(payload.get("freeze_room", True))
    soft_lock_penalty = int(payload.get("soft_lock_penalty", 1000))
    slot_minutes = int(payload.get("slot_minutes", 30))
    include_soft_ids = {int(val) for val in payload.get("include_soft_relock_ids", [])}
    regenerate_ids = {int(val) for val in payload.get("regenerate_ids", [])}

    week_start = _parse_week_start(base_version_label)

    base_version = (
        PlanningVersion.query.filter_by(label=base_version_label)
        .order_by(PlanningVersion.revision.desc())
        .first()
    )
    if base_version is None:
        raise NotFound(f"Planning version '{base_version_label}' not found")

    locked_records = (
        SessionValidated.query.filter_by(version_id=base_version.id)
        .order_by(SessionValidated.start_dt)
        .all()
    )

    locked_payload: List[Dict[str, Any]] = []
    new_sessions: List[MutableMapping[str, Any]] = [
        dict(entry) for entry in payload.get("new_sessions", [])
    ]

    total_slots = (7 * 24 * 60) // slot_minutes

    locked_kept: List[SessionValidated] = []
    for record in locked_records:
        start_slot, end_slot = to_slots(record.start_dt, record.end_dt, week_start, slot_minutes)
        duration = end_slot - start_slot
        base_info = {
            "id": record.id,
            "teacher_id": record.teacher_id,
            "group_id": record.group_id,
            "room_id": record.room_id,
            "start_dt": record.start_dt,
            "end_dt": record.end_dt,
        }
        if record.id in include_soft_ids or record.id in regenerate_ids:
            session_data: Dict[str, Any] = {
                "id": record.id,
                "course_id": record.course_id,
                "teacher_id": record.teacher_id,
                "group_id": record.group_id,
                "room_id": record.room_id,
                "duration_slots": duration,
                "start_min_slot": 0,
                "start_max_slot": max(total_slots - duration, 0),
            }
            if record.room_id is not None:
                session_data.setdefault("room_ids", [record.room_id])
            if record.id in include_soft_ids:
                soft_lock = {"start_slot": start_slot, "penalty": soft_lock_penalty}
                if record.room_id is not None:
                    soft_lock["room_id"] = record.room_id
                session_data["soft_lock"] = soft_lock
            new_sessions.append(session_data)
        else:
            locked_payload.append(base_info)
            locked_kept.append(record)

    params = {
        "day0": week_start,
        "freeze_room": freeze_room,
        "soft_lock_penalty": soft_lock_penalty,
        "slot_minutes": slot_minutes,
    }

    try:
        model = build_incremental_model(locked_payload, new_sessions, params)
    except Exception as exc:  # pragma: no cover - defensive guard
        current_app.logger.exception("Failed to build incremental model")
        raise BadRequest(str(exc)) from exc

    solver, status = solve_model(
        model,
        payload.get("time_limit_s"),
        payload.get("workers"),
        payload.get("seed"),
    )

    status_label = STATUS_LABELS.get(status, f"STATUS_{int(status)}")

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return jsonify({"status": status_label, "message": "No feasible solution"}), 409

    max_revision = (
        db.session.query(func.max(PlanningVersion.revision))
        .filter(PlanningVersion.label == base_version_label)
        .scalar()
        or 0
    )
    new_revision = max_revision + 1
    new_label = f"{base_version_label}-rev{new_revision}"

    new_version = PlanningVersion(label=new_label, revision=new_revision)
    db.session.add(new_version)
    db.session.flush()

    for record in locked_kept:
        clone = record.clone_for_version(new_version)
        db.session.add(clone)

    soft_lock_moved = 0
    planned_sessions: List[SessionValidated] = []

    for session in new_sessions:
        cp_vars = session.get("_cp_vars") or {}
        start_var = cp_vars.get("start")
        duration = cp_vars.get("duration")
        if start_var is None or duration is None:
            current_app.logger.warning("Session missing solver variables: %s", session)
            continue
        start_slot = solver.Value(start_var)
        end_slot = start_slot + int(duration)
        start_dt = from_slot(start_slot, week_start, slot_minutes)
        end_dt = from_slot(end_slot, week_start, slot_minutes)

        room_id = session.get("room_id")
        room_choice = cp_vars.get("room_choice")
        if room_choice is not None:
            room_id = solver.Value(room_choice)
        else:
            room_literals: Dict[int, Any] = cp_vars.get("room_literals") or {}
            for rid, lit in room_literals.items():
                if solver.BooleanValue(lit):
                    room_id = rid
                    break

        break_time = cp_vars.get("break_time")
        break_room = cp_vars.get("break_room")
        if break_time is not None and solver.BooleanValue(break_time):
            soft_lock_moved += 1
        elif break_room is not None and solver.BooleanValue(break_room):
            soft_lock_moved += 1

        planned = SessionValidated(
            course_id=int(session.get("course_id", 0)),
            teacher_id=int(session.get("teacher_id")),
            group_id=int(session.get("group_id")),
            room_id=int(room_id) if room_id is not None else None,
            start_dt=start_dt,
            end_dt=end_dt,
            version=new_version,
        )
        db.session.add(planned)
        planned_sessions.append(planned)

    db.session.commit()

    all_sessions = [*new_version.sessions]
    summary = {
        "locked_count": len(locked_kept),
        "planned_count": len(planned_sessions),
        "soft_lock_moved": soft_lock_moved,
    }

    response = {
        "status": status_label,
        "version_label": new_version.label,
        "revision": new_version.revision,
        "summary": summary,
        "sessions": [_serialise_session(session) for session in all_sessions],
    }

    return jsonify(response)
