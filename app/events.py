from __future__ import annotations

from collections.abc import Iterable
from datetime import timedelta
from typing import List

from .models import Session
from .scheduler import EXTENDED_BREAKS, MAX_SLOT_GAP


def _normalise_label(label: str | None) -> str:
    if not label:
        return ""
    return label.strip().upper()


def _sessions_can_chain(previous: Session, current: Session) -> bool:
    if previous.course_id != current.course_id:
        return False
    if previous.class_group_id != current.class_group_id:
        return False
    if previous.attendee_ids() != current.attendee_ids():
        return False
    if previous.teacher_id != current.teacher_id:
        return False
    if _normalise_label(previous.subgroup_label) != _normalise_label(current.subgroup_label):
        return False
    if previous.start_time.date() != current.start_time.date():
        return False
    gap = current.start_time - previous.end_time
    if gap < timedelta(0):
        return False
    if gap <= MAX_SLOT_GAP:
        return True
    # Les pauses étendues (midi, fin de matinée, etc.) doivent interrompre
    # l'affichage groupé afin de refléter les coupures dans l'emploi du temps.
    if (previous.end_time.time(), current.start_time.time()) in EXTENDED_BREAKS:
        return False
    return False


def _build_event_from_group(group: List[Session]) -> dict[str, object]:
    first = group[0]
    event = first.as_event()
    ordered_rooms: list[str] = []
    segments: list[dict[str, str]] = []
    extended = event.setdefault("extendedProps", {})
    required_softwares = set(extended.get("course_softwares") or [])
    available_softwares = set(extended.get("room_softwares") or [])
    missing_softwares = set(extended.get("missing_softwares") or [])
    class_names: set[str] = set()
    for session in group:
        room_name = session.room.name
        if room_name not in ordered_rooms:
            ordered_rooms.append(room_name)
        segments.append(
            {
                "id": str(session.id),
                "start": session.start_time.isoformat(),
                "end": session.end_time.isoformat(),
                "room": room_name,
            }
        )
        required_softwares.update(software.name for software in session.course.softwares)
        available_softwares.update(software.name for software in session.room.softwares)
        room_software_ids = {software.id for software in session.room.softwares}
        missing_softwares.update(
            software.name
            for software in session.course.softwares
            if software.id not in room_software_ids
        )
        class_names.update(session.attendee_names())
    event["start"] = group[0].start_time.isoformat()
    event["end"] = group[-1].end_time.isoformat()
    room_label = ", ".join(ordered_rooms) or first.room.name
    event["title"] = first.title_with_room(room_label)
    extended["room"] = room_label
    extended["rooms"] = ordered_rooms
    extended["segments"] = segments
    extended["segment_ids"] = [segment["id"] for segment in segments]
    extended["is_grouped"] = len(group) > 1
    extended["course_softwares"] = sorted(required_softwares)
    extended["room_softwares"] = sorted(available_softwares)
    extended["missing_softwares"] = sorted(missing_softwares)
    if class_names:
        class_list = sorted(class_names, key=str.lower)
        extended["class_group"] = ", ".join(class_list)
        extended["class_groups"] = class_list
    if len(group) > 1:
        event["id"] = "group-" + "-".join(extended["segment_ids"])
    return event


def sessions_to_grouped_events(sessions: Iterable[Session]) -> list[dict[str, object]]:
    sorted_sessions = sorted(
        sessions,
        key=lambda session: (
            session.class_group_id,
            _normalise_label(session.subgroup_label),
            session.course_id,
            session.teacher_id,
            session.start_time,
        ),
    )
    grouped_events: list[dict[str, object]] = []
    current_group: list[Session] = []
    for session in sorted_sessions:
        if not current_group:
            current_group = [session]
            continue
        previous = current_group[-1]
        if _sessions_can_chain(previous, session):
            current_group.append(session)
            continue
        grouped_events.append(_build_event_from_group(current_group))
        current_group = [session]
    if current_group:
        grouped_events.append(_build_event_from_group(current_group))
    return grouped_events
