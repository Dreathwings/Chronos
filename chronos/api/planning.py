"""REST endpoints for incremental planning generation."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, MutableMapping

from flask import current_app, jsonify, request
from ortools.sat.python import cp_model
from sqlalchemy import func

from app import db
from app.models import PlanningVersion, Session, SessionValidated

from chronos.api import api_bp
from chronos.solver.incremental import (
    build_incremental_model,
    from_slot,
    solve_model,
    to_slots,
)

WEEK_MINUTES = 7 * 24 * 60

_STATUS_LABELS = {
    cp_model.OPTIMAL: "OPTIMAL",
    cp_model.FEASIBLE: "FEASIBLE",
    cp_model.INFEASIBLE: "INFEASIBLE",
    cp_model.MODEL_INVALID: "MODEL_INVALID",
    cp_model.UNKNOWN: "UNKNOWN",
}


def _parse_week_label(label: str) -> datetime:
    try:
        year_str, week_str = label.split("-")
        return datetime.fromisocalendar(int(year_str), int(week_str), 1)
    except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
        raise ValueError("Invalid base_version; expected YYYY-WW") from exc


def _coerce_int_set(values: Iterable[Any] | None) -> set[int]:
    if not values:
        return set()
    result: set[int] = set()
    for value in values:
        try:
            result.add(int(value))
        except (TypeError, ValueError):
            continue
    return result


def _serialise_session(session: SessionValidated) -> dict[str, Any]:
    return {
        "id": session.id,
        "course_id": session.course_id,
        "teacher_id": session.teacher_id,
        "group_id": session.group_id,
        "room_id": session.room_id,
        "start": session.start_dt.isoformat(),
        "end": session.end_dt.isoformat(),
        "version_id": session.version_id,
    }


def _clone_validated_session(
    source: SessionValidated, version: PlanningVersion
) -> SessionValidated:
    clone = SessionValidated(
        course_id=source.course_id,
        teacher_id=source.teacher_id,
        group_id=source.group_id,
        room_id=source.room_id,
        start_dt=source.start_dt,
        end_dt=source.end_dt,
        version=version,
    )
    db.session.add(clone)
    return clone


def _session_duration_slots(
    start_dt: datetime | None,
    end_dt: datetime | None,
    slot_minutes: int,
    day0: datetime,
) -> tuple[int, int, int]:
    if start_dt is None or end_dt is None:
        raise ValueError("Sessions must include start and end datetimes")
    start_slot, end_slot = to_slots(start_dt, end_dt, day0, slot_minutes)
    duration = end_slot - start_slot
    if duration <= 0:
        raise ValueError("Unable to compute a positive duration for session")
    return start_slot, end_slot, duration


def _build_new_session_payload(
    session_obj: Session | SessionValidated,
    day0: datetime,
    slot_minutes: int,
    total_slots: int,
    soft_lock: bool,
) -> MutableMapping[str, Any]:
    start_dt = getattr(session_obj, "start_dt", None) or getattr(
        session_obj, "start_time", None
    )
    end_dt = getattr(session_obj, "end_dt", None) or getattr(
        session_obj, "end_time", None
    )
    start_slot, end_slot, duration = _session_duration_slots(
        start_dt, end_dt, slot_minutes, day0
    )

    start_min = 0
    start_max = max(total_slots - duration, start_min)

    payload: MutableMapping[str, Any] = {
        "id": getattr(session_obj, "id", None),
        "course_id": getattr(session_obj, "course_id", None),
        "teacher_id": getattr(session_obj, "teacher_id", None),
        "group_id": getattr(session_obj, "group_id", None)
        or getattr(session_obj, "class_group_id", None),
        "duration_slots": duration,
        "start_min_slot": start_min,
        "start_max_slot": start_max,
        "room_candidates": None,
        "room_id": getattr(session_obj, "room_id", None),
        "original_start_dt": start_dt,
        "original_end_dt": end_dt,
    }

    room_id = getattr(session_obj, "room_id", None)
    if room_id is not None:
        payload["room_candidates"] = [int(room_id)]

    if soft_lock:
        soft_payload = {"start_slot": start_slot}
        if room_id is not None:
            soft_payload["room_id"] = int(room_id)
        payload["soft_lock"] = soft_payload

    return payload


def _status_label(status: int) -> str:
    return _STATUS_LABELS.get(status, f"STATUS_{status}")


@api_bp.post("/generate")
def generate_planning() -> tuple[Any, int]:
    mode = request.args.get("mode")
    if mode != "incremental":
        return jsonify({"error": "Unsupported mode"}), 400

    base_version_label = request.args.get("base_version")
    if not base_version_label:
        return jsonify({"error": "Missing base_version parameter"}), 400

    try:
        day0 = _parse_week_label(base_version_label)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    payload = request.get_json(silent=True) or {}
    freeze_room = bool(payload.get("freeze_room", True))
    soft_lock_penalty = int(payload.get("soft_lock_penalty", 0))
    if soft_lock_penalty < 0:
        soft_lock_penalty = 0
    include_soft_ids = _coerce_int_set(payload.get("include_soft_relock_ids"))
    regenerate_ids = _coerce_int_set(payload.get("regenerate_ids"))
    slot_minutes = int(payload.get("slot_minutes", 30))
    if slot_minutes <= 0:
        return jsonify({"error": "slot_minutes must be positive"}), 400

    time_limit_raw = payload.get("time_limit_s")
    workers_raw = payload.get("workers")
    seed_raw = payload.get("seed")

    def _coerce_optional_number(value: Any, cast: type) -> Any:
        if value is None:
            return None
        try:
            return cast(value)
        except (TypeError, ValueError):
            return None

    time_limit_s = _coerce_optional_number(time_limit_raw, float)
    workers = _coerce_optional_number(workers_raw, int)
    seed = _coerce_optional_number(seed_raw, int)

    total_slots = WEEK_MINUTES // slot_minutes

    base_version = (
        PlanningVersion.query.filter_by(label=base_version_label)
        .order_by(PlanningVersion.revision.desc())
        .first()
    )
    if base_version is None:
        return jsonify({"error": "Base version not found"}), 404

    validated_sessions = (
        SessionValidated.query.filter_by(version_id=base_version.id).all()
    )
    locked_by_id = {session.id: session for session in validated_sessions}

    locked_sessions: list[SessionValidated] = []
    for session in validated_sessions:
        if session.id in include_soft_ids or session.id in regenerate_ids:
            continue
        locked_sessions.append(session)

    new_session_payloads: list[MutableMapping[str, Any]] = []
    soft_lock_flags: set[int] = set()

    for session_id in include_soft_ids:
        session = locked_by_id.get(session_id)
        if not session:
            continue
        soft_lock_flags.add(session_id)
        new_session_payloads.append(
            _build_new_session_payload(session, day0, slot_minutes, total_slots, True)
        )

    for session_id in regenerate_ids:
        if session_id in soft_lock_flags:
            continue
        session = locked_by_id.get(session_id)
        if session is not None:
            new_session_payloads.append(
                _build_new_session_payload(session, day0, slot_minutes, total_slots, False)
            )
            continue
        candidate = Session.query.get(session_id)
        if candidate is not None:
            new_session_payloads.append(
                _build_new_session_payload(
                    candidate, day0, slot_minutes, total_slots, False
                )
            )

    locked_entries = [
        {
            "id": session.id,
            "start_dt": session.start_dt,
            "end_dt": session.end_dt,
            "teacher_id": session.teacher_id,
            "group_id": session.group_id,
            "room_id": session.room_id,
        }
        for session in locked_sessions
    ]

    params = {
        "day0": day0,
        "freeze_room": freeze_room,
        "soft_lock_penalty": soft_lock_penalty,
        "slot_minutes": slot_minutes,
    }

    try:
        model = build_incremental_model(locked_entries, new_session_payloads, params)
    except ValueError as exc:
        current_app.logger.exception("Failed to build incremental model: %s", exc)
        return jsonify({"error": str(exc)}), 400

    solver, status = solve_model(model, time_limit_s, workers, seed)
    status_label = _status_label(status)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return jsonify({"status": status_label, "error": "No feasible solution"}), 409

    max_revision = (
        db.session.query(func.max(PlanningVersion.revision))
        .filter(PlanningVersion.label == base_version_label)
        .scalar()
        or 0
    )
    new_version = PlanningVersion(label=base_version_label, revision=int(max_revision) + 1)
    db.session.add(new_version)
    db.session.flush()

    created_sessions: list[SessionValidated] = []
    for session in locked_sessions:
        created_sessions.append(_clone_validated_session(session, new_version))

    soft_moved = 0
    for payload in new_session_payloads:
        variables = payload.get("variables") or {}
        duration = int(payload["duration_slots"])
        start_value = solver.Value(variables["start"])
        start_dt = from_slot(start_value, day0, slot_minutes)
        end_dt = from_slot(start_value + duration, day0, slot_minutes)

        room_id = None
        room_var = variables.get("room_var")
        if room_var is not None:
            room_id = int(solver.Value(room_var))
        else:
            room_literals = variables.get("room_literals") or {}
            for candidate, literal in room_literals.items():
                if solver.BooleanValue(literal):
                    room_id = int(candidate)
                    break
            if room_id is None:
                assigned_room = variables.get("assigned_room")
                if assigned_room is not None:
                    room_id = int(assigned_room)
            if room_id is None:
                candidates = payload.get("room_candidates") or []
                if candidates:
                    room_id = int(candidates[0])
                elif payload.get("room_id") is not None:
                    room_id = int(payload["room_id"])

        keep_time_var = variables.get("keep_time")
        keep_room_var = variables.get("keep_room")
        kept_time = keep_time_var is None or solver.BooleanValue(keep_time_var)
        kept_room = keep_room_var is None or solver.BooleanValue(keep_room_var)
        if not (kept_time and kept_room):
            soft_moved += 1

        validated = SessionValidated(
            course_id=payload.get("course_id"),
            teacher_id=payload.get("teacher_id"),
            group_id=payload.get("group_id"),
            room_id=room_id,
            start_dt=start_dt,
            end_dt=end_dt,
            version=new_version,
        )
        db.session.add(validated)
        created_sessions.append(validated)

    db.session.commit()

    response_sessions = [_serialise_session(session) for session in created_sessions]

    summary = {
        "locked": len(locked_sessions),
        "replanned": len(new_session_payloads),
        "soft_moved": soft_moved,
    }

    version_label = f"{new_version.label}-r{new_version.revision}"

    return (
        jsonify(
            {
                "status": status_label,
                "version": version_label,
                "summary": summary,
                "sessions": response_sessions,
            }
        ),
        200,
    )
