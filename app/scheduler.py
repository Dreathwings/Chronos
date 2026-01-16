from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta
from typing import Iterable, List, Optional, Set

from . import db
from .models import (
    ClassGroup,
    Course,
    CourseClassLink,
    ClosingPeriod,
    Room,
    Session,
    Teacher,
)
from .planning.constants import (
    EXTENDED_BREAKS,
    MAX_SLOT_GAP,
    SCHEDULE_SLOTS,
    START_TIMES,
    WORKING_WINDOWS,
    collect_contiguous_slots,
    fits_in_windows,
)
from .planning.reporting import ScheduleReporter, suggest_schedule_recovery
from .planning.utils import daterange, overlaps, week_bounds, week_start_for
from .progress import NullScheduleProgress, ScheduleProgress

COURSE_TYPE_CHRONOLOGY: dict[str, int] = {
    "CM": 0,
    "TD": 1,
    "TP": 2,
    "TEST": 3,
    "EVAL": 3,
    "Eval": 3,
}


class TeacherAllocationState:
    def __init__(self, course: Course) -> None:
        self.course = course
        self.targets = dict(course.teacher_allocation_map)
        self.remaining = {teacher_id: float(hours) for teacher_id, hours in self.targets.items()}
        for session in course.sessions:
            teacher_id = session.teacher_id
            if teacher_id is None:
                continue
            duration = float(session.duration_hours)
            if teacher_id in self.remaining:
                self.remaining[teacher_id] = max(self.remaining[teacher_id] - duration, 0.0)

    def remaining_hours(self, teacher_id: int | None) -> float | None:
        if teacher_id is None:
            return None
        if teacher_id not in self.remaining:
            return None
        return max(self.remaining[teacher_id], 0.0)

    def can_allocate(self, teacher_id: int | None, duration_hours: float) -> bool:
        if teacher_id is None:
            return False
        target = self.targets.get(teacher_id)
        if target is None:
            return True
        return self.remaining.get(teacher_id, 0.0) >= max(duration_hours, 0.0)

    def consume(self, teacher_id: int | None, duration_hours: float) -> None:
        if teacher_id is None:
            return
        if teacher_id not in self.remaining:
            return
        self.remaining[teacher_id] = max(
            self.remaining[teacher_id] - max(duration_hours, 0.0),
            0.0,
        )


_ALLOCATION_STATE: dict[int, TeacherAllocationState] = {}


def _set_allocation_state(course: Course, state: TeacherAllocationState) -> None:
    _ALLOCATION_STATE[id(course)] = state


def _get_allocation_state(course: Course) -> TeacherAllocationState | None:
    return _ALLOCATION_STATE.get(id(course))


def _clear_allocation_state(course: Course) -> None:
    _ALLOCATION_STATE.pop(id(course), None)


def _register_created_sessions(
    course: Course, sessions: Iterable[Session], created_sessions: list[Session]
) -> None:
    created_sessions.extend(sessions)
    allocation_state = _get_allocation_state(course)
    if not allocation_state:
        return
    for session in sessions:
        allocation_state.consume(session.teacher_id, float(session.duration_hours))


def _course_type_priority(course_type: str | None) -> int | None:
    if not course_type:
        return None
    priority = COURSE_TYPE_CHRONOLOGY.get(course_type)
    if priority is not None:
        return priority
    return COURSE_TYPE_CHRONOLOGY.get(course_type.upper())


def _closed_days_between(start: date, end: date) -> set[date]:
    if start > end:
        return set()
    closed: set[date] = set()
    for period in ClosingPeriod.ordered_periods():
        if period.end_date < start:
            continue
        if period.start_date > end:
            break
        span_start = max(period.start_date, start)
        span_end = min(period.end_date, end)
        for day in daterange(span_start, span_end):
            closed.add(day)
    return closed




class PlacementDiagnostics:
    def __init__(self) -> None:
        self.teacher_reasons: set[str] = set()
        self.room_reasons: set[str] = set()
        self.class_reasons: set[str] = set()
        self.other_reasons: set[str] = set()

    def add_teacher(self, message: str | None) -> None:
        if message:
            self.teacher_reasons.add(message)

    def add_room(self, message: str | None) -> None:
        if message:
            self.room_reasons.add(message)

    def add_class(self, message: str | None) -> None:
        if message:
            self.class_reasons.add(message)

    def add_other(self, message: str | None) -> None:
        if message:
            self.other_reasons.add(message)

    def emit(
        self,
        reporter: ScheduleReporter | None,
        *,
        context_label: str,
        day: date,
    ) -> None:
        if reporter is None:
            return
        day_label = day.strftime("%d/%m/%Y")
        for message in sorted(self.class_reasons):
            reporter.warning(f"{context_label} — {day_label} : {message}")
        for message in sorted(self.teacher_reasons):
            reporter.warning(f"{context_label} — {day_label} : {message}")
        for message in sorted(self.room_reasons):
            reporter.warning(f"{context_label} — {day_label} : {message}")
        for message in sorted(self.other_reasons):
            reporter.warning(f"{context_label} — {day_label} : {message}")
        if not any(
            (
                self.class_reasons,
                self.teacher_reasons,
                self.room_reasons,
                self.other_reasons,
            )
        ):
            reporter.warning(
                f"{context_label} — {day_label} : aucune option compatible trouvée sur ce créneau."
            )


def find_available_room(
    course: Course,
    start: datetime,
    end: datetime,
    *,
    required_capacity: int | None = None,
) -> Optional[Room]:
    rooms = Room.query.order_by(Room.capacity.asc(), Room.name.asc()).all()
    preferred_rooms: list[Room] = []
    preferred_room_ids: set[int] = set()
    if course.preferred_rooms:
        preferred_rooms = sorted(
            [room for room in course.preferred_rooms if room is not None],
            key=lambda room: (room.capacity or 0, (room.name or "").lower()),
        )
        preferred_room_ids = {room.id for room in preferred_rooms if room.id}
    ordered_rooms: list[Room] = []
    ordered_rooms.extend(preferred_rooms)
    ordered_rooms.extend(room for room in rooms if room.id not in preferred_room_ids)
    required_students = required_capacity or 1
    required_posts = course.required_computer_posts()
    required_equipment_ids = {equipment.id for equipment in course.equipments}
    required_software_ids = {software.id for software in course.softwares}

    best_room: Room | None = None
    best_missing_softwares: int | None = None

    for room in ordered_rooms:
        if room.capacity < required_students:
            continue
        if required_posts and (room.computers or 0) < required_posts:
            continue

        room_equipment_ids = {equipment.id for equipment in room.equipments}
        if required_equipment_ids.difference(room_equipment_ids):
            continue

        room_software_ids = {software.id for software in room.softwares}
        missing_softwares = required_software_ids.difference(room_software_ids)

        conflict = False
        for session in room.sessions:
            if overlaps(session.start_time, session.end_time, start, end):
                conflict = True
                break
        if conflict:
            continue

        missing_count = len(missing_softwares)
        if best_room is None or best_missing_softwares is None or missing_count < best_missing_softwares:
            best_room = room
            best_missing_softwares = missing_count
            if missing_count == 0:
                break

    return best_room


def _format_session_label(session: Session) -> str:
    start_label = session.start_time.strftime("%d/%m %H:%M")
    end_label = session.end_time.strftime("%H:%M")
    return f"{session.course.name} ({start_label} → {end_label})"


def _describe_teacher_unavailability(
    course: Course,
    start: datetime,
    end: datetime,
    *,
    link: CourseClassLink | None = None,
    subgroup_label: str | None = None,
    segments: Optional[list[tuple[datetime, datetime]]] = None,
) -> str:
    duration_hours = max((end - start).total_seconds() / 3600.0, 0.0)
    allocation_state = _get_allocation_state(course)
    preferred: list[Teacher] = []
    if link is not None:
        for assigned in link.preferred_teachers(subgroup_label):
            if assigned is not None and assigned not in preferred:
                preferred.append(assigned)

    link_teachers = link.assigned_teachers() if link is not None else []
    course_teachers = [
        teacher for teacher in getattr(course, "teachers", []) if teacher is not None
    ]

    fallback_pool: list[Teacher]
    if link_teachers or course_teachers:
        fallback_pool = list(link_teachers)
        for teacher in course_teachers:
            if teacher not in fallback_pool:
                fallback_pool.append(teacher)
    else:
        fallback_pool = Teacher.query.all()

    candidates = preferred + [teacher for teacher in fallback_pool if teacher not in preferred]
    if not candidates:
        return "Aucun enseignant n'est associé au cours."

    segments_to_check = segments or [(start, end)]
    reasons: list[str] = []
    exhausted: list[str] = []
    for teacher in sorted(candidates, key=lambda t: t.name.lower()):
        if not all(
            teacher.is_available_during(segment_start, segment_end)
            for segment_start, segment_end in segments_to_check
        ):
            reasons.append(f"{teacher.name} est déclaré indisponible sur ce créneau.")
            continue
        if allocation_state and not allocation_state.can_allocate(
            teacher.id, duration_hours
        ):
            exhausted.append(teacher.name)
            continue
        conflicts = [
            _format_session_label(session)
            for session in teacher.sessions
            for segment_start, segment_end in segments_to_check
            if overlaps(session.start_time, session.end_time, segment_start, segment_end)
        ]
        if conflicts:
            summary = ", ".join(conflicts[:2])
            if len(conflicts) > 2:
                summary += ", …"
            reasons.append(f"{teacher.name} est déjà planifié : {summary}")
            continue
    if exhausted:
        reasons.append(
            "Quota d'heures atteint pour : " + ", ".join(sorted(exhausted, key=str.lower))
        )
    if reasons:
        return " ; ".join(reasons)
    teacher_names = ", ".join(sorted(teacher.name for teacher in candidates))
    return f"Aucun enseignant disponible parmi : {teacher_names}."


def _describe_room_unavailability(
    course: Course,
    start: datetime,
    end: datetime,
    *,
    required_capacity: int | None = None,
) -> str:
    rooms = Room.query.order_by(Room.capacity.asc()).all()
    if not rooms:
        return "Aucune salle n'est enregistrée dans la base."

    required_students = required_capacity or 1
    required_posts = course.required_computer_posts()
    capacity_rejects: list[str] = []
    computer_rejects: list[str] = []
    equipment_counter: Counter[str] = Counter()
    software_counter: Counter[str] = Counter()
    conflicts: list[str] = []
    compatible_rooms: list[Room] = []

    required_equipment_ids = {equipment.id for equipment in course.equipments}
    required_software_ids = {software.id for software in course.softwares}

    for room in rooms:
        if room.capacity < required_students:
            capacity_rejects.append(room.name)
            continue
        if required_posts and (room.computers or 0) < required_posts:
            computer_rejects.append(room.name)
            continue
        room_equipment_ids = {equipment.id for equipment in room.equipments}
        missing_equipment = required_equipment_ids.difference(room_equipment_ids)
        if missing_equipment:
            for equipment_id in missing_equipment:
                equipment = next(
                    (item for item in course.equipments if item.id == equipment_id),
                    None,
                )
                if equipment is not None:
                    equipment_counter[equipment.name] += 1
            continue
        room_software_ids = {software.id for software in room.softwares}
        missing_softwares = required_software_ids.difference(room_software_ids)
        if missing_softwares:
            for software_id in missing_softwares:
                software = next(
                    (item for item in course.softwares if item.id == software_id),
                    None,
                )
                if software is not None:
                    software_counter[software.name] += 1
            continue
        compatible_rooms.append(room)

    for room in compatible_rooms:
        overlapping = [
            _format_session_label(session)
            for session in room.sessions
            if overlaps(session.start_time, session.end_time, start, end)
        ]
        if overlapping:
            label = f"{room.name} occupée par {', '.join(overlapping[:2])}"
            if len(overlapping) > 2:
                label += ", …"
            conflicts.append(label)

    parts: list[str] = []
    if capacity_rejects:
        if len(capacity_rejects) == len(rooms):
            parts.append("Aucune salle n'atteint la capacité requise.")
        else:
            display = ", ".join(sorted(capacity_rejects[:3]))
            if len(capacity_rejects) > 3:
                display += ", …"
            parts.append(f"Salles trop petites : {display}")
    if required_posts and computer_rejects:
        if len(computer_rejects) == len(rooms) - len(capacity_rejects):
            parts.append(
                "Aucune salle ne dispose du nombre de postes informatiques requis."
            )
        else:
            display = ", ".join(sorted(computer_rejects[:3]))
            if len(computer_rejects) > 3:
                display += ", …"
            parts.append(f"Sans nombre de postes suffisant : {display}")
    if equipment_counter:
        equipment_display = ", ".join(
            f"{name} ({count})" for name, count in equipment_counter.most_common(3)
        )
        if len(equipment_counter) > 3:
            equipment_display += ", …"
        parts.append(f"Équipements manquants : {equipment_display}")
    if software_counter:
        software_display = ", ".join(
            f"{name} ({count})" for name, count in software_counter.most_common(3)
        )
        if len(software_counter) > 3:
            software_display += ", …"
        parts.append(f"Logiciels manquants : {software_display}")
    if conflicts:
        conflict_display = "; ".join(conflicts[:2])
        if len(conflicts) > 2:
            conflict_display += "; …"
        parts.append(f"Salles déjà réservées : {conflict_display}")

    if not parts:
        return "Aucune salle compatible n'est disponible sur ce créneau."
    return " ; ".join(parts)


def _week_bounds(day: date) -> tuple[date, date]:
    return week_bounds(day)


def _session_involves_class(session: Session, class_group: ClassGroup) -> bool:
    if session.class_group_id == class_group.id:
        return True
    attendees = session.attendees or []
    return any(att.id == class_group.id for att in attendees)


def _class_sessions_in_week(
    class_group: ClassGroup,
    week_start: date,
    week_end: date,
    pending_sessions: Iterable[Session] = (),
    *,
    subgroup_label: str | None = None,
    ignore_session_id: int | None = None,
) -> Iterable[Session]:
    target_label = _normalise_label(subgroup_label) if subgroup_label is not None else None

    def _matches_scope(session: Session) -> bool:
        if not _session_involves_class(session, class_group):
            return False
        if target_label is None:
            return True
        session_label = _normalise_label(session.subgroup_label)
        if session_label and session_label != target_label:
            return False
        return True

    seen: set[int] = set()
    for session in class_group.all_sessions:
        if ignore_session_id is not None and session.id == ignore_session_id:
            continue
        marker = id(session)
        if marker in seen:
            continue
        if not _matches_scope(session):
            continue
        session_day = session.start_time.date()
        if week_start <= session_day <= week_end:
            seen.add(marker)
            yield session
    for session in pending_sessions:
        if ignore_session_id is not None and session.id == ignore_session_id:
            continue
        marker = id(session)
        if marker in seen:
            continue
        if not _matches_scope(session):
            continue
        session_day = session.start_time.date()
        if week_start <= session_day <= week_end:
            seen.add(marker)
            yield session


def _class_sessions_on_day(
    class_group: ClassGroup,
    day: date,
    *,
    pending_sessions: Iterable[Session] = (),
    subgroup_label: str | None = None,
) -> list[Session]:
    target_label = _normalise_label(subgroup_label) if subgroup_label is not None else None
    collected: list[Session] = []
    seen: set[int] = set()

    for collection in (class_group.all_sessions, pending_sessions):
        for session in collection:
            if session is None or session.start_time is None:
                continue
            marker = session.id if session.id is not None else id(session)
            if marker in seen:
                continue
            if not _session_involves_class(session, class_group):
                continue
            if target_label is not None:
                session_label = _normalise_label(session.subgroup_label)
                if session_label and session_label != target_label:
                    continue
            if session.start_time.date() != day:
                continue
            collected.append(session)
            seen.add(marker)

    return sorted(collected, key=lambda s: (s.start_time, s.id or 0))


def _course_family_key(course: Course) -> tuple[str, int | str, str | None]:
    semester = (course.semester or "").strip().upper() or None
    if course.course_name_id is not None:
        return ("course-name-id", course.course_name_id, semester)
    configured = course.configured_name
    if configured is not None and configured.name:
        return ("course-name", configured.name.lower(), semester)
    if course.id is not None:
        return ("course-id", course.id, semester)
    return ("course-name", (course.name or "").lower(), semester)


def format_class_label(
    class_group: ClassGroup,
    *,
    link: CourseClassLink | None = None,
    subgroup_label: str | None = None,
) -> str:
    base = class_group.name
    if subgroup_label:
        label = (subgroup_label or "").strip().upper()
        subgroup_name: str | None = None
        if link is not None:
            subgroup_name = link.subgroup_name_for(subgroup_label)
        else:
            subgroup_name = None
        if subgroup_name:
            return f"{base} — {subgroup_name}"
        if label:
            return f"{base} — groupe {label}"
    return base


def _day_respects_chronology(
    course: Course,
    class_group: ClassGroup,
    day: date,
    pending_sessions: Iterable[Session] = (),
    *,
    subgroup_label: str | None = None,
    ignore_session_id: int | None = None,
    candidate_start: datetime | None = None,
) -> bool:
    priority = _course_type_priority(course.course_type)
    if priority is None:
        return True
    family_key = _course_family_key(course)
    semester = family_key[2]
    target_label = _normalise_label(subgroup_label) if subgroup_label is not None else None

    def _iter_sessions() -> Iterable[Session]:
        seen: set[int] = set()
        for collection in (class_group.all_sessions, pending_sessions):
            for session in collection:
                if session is None or session.start_time is None:
                    continue
                if ignore_session_id and session.id == ignore_session_id:
                    continue
                marker = session.id if session.id is not None else id(session)
                if marker in seen:
                    continue
                seen.add(marker)
                yield session

    week_start, week_end = _week_bounds(day)
    candidate_day = (
        candidate_start.date() if isinstance(candidate_start, datetime) else day
    )

    for session in _iter_sessions():
        if not _session_involves_class(session, class_group):
            continue
        if target_label is not None:
            session_label = _normalise_label(session.subgroup_label)
            if session_label and session_label != target_label:
                continue
        other_course = session.course
        if other_course is None:
            continue
        if _course_family_key(other_course) != family_key:
            continue
        other_semester = (other_course.semester or "").strip().upper() or None
        if other_semester != semester:
            continue
        other_priority = _course_type_priority(other_course.course_type)
        if other_priority is None or other_priority == priority:
            continue
        session_start = session.start_time
        session_day = session_start.date()
        if session_day < week_start or session_day > week_end:
            continue
        if candidate_start is not None and session_day == candidate_day:
            if other_priority < priority and session_start > candidate_start:
                return False
            if other_priority > priority and session_start < candidate_start:
                return False
            continue
        if other_priority < priority and session_day > day:
            return False
        if other_priority > priority and session_day < day:
            return False
    return True


def _course_sessions_in_week(
    course: Course,
    week_start: date,
    week_end: date,
    pending_sessions: Iterable[Session] = (),
    *,
    ignore_session_id: int | None = None,
) -> Iterable[Session]:
    def _matches(session: Session | None) -> bool:
        if session is None or session.start_time is None:
            return False
        if ignore_session_id and session.id == ignore_session_id:
            return False
        day = session.start_time.date()
        return week_start <= day <= week_end

    seen: set[int] = set()

    for session in course.sessions:
        if not _matches(session):
            continue
        key = session.id or id(session)
        if key in seen:
            continue
        seen.add(key)
        yield session

    for session in pending_sessions:
        if session is None:
            continue
        session_course = getattr(session, "course", None)
        session_course_id = getattr(session, "course_id", None)
        if session_course is not None and session_course.id != course.id:
            continue
        if session_course is None and session_course_id != course.id:
            continue
        if not _matches(session):
            continue
        key = session.id or id(session)
        if key in seen:
            continue
        seen.add(key)
        yield session


def _course_hours_in_week(
    course: Course,
    week_start: date,
    week_end: date,
    pending_sessions: Iterable[Session] = (),
    *,
    ignore_session_id: int | None = None,
) -> int:
    return sum(
        session.duration_hours
        for session in _course_sessions_in_week(
            course,
            week_start,
            week_end,
            pending_sessions,
            ignore_session_id=ignore_session_id,
        )
    )


def _course_class_sessions_in_week(
    course: Course,
    class_group: ClassGroup,
    week_start: date,
    week_end: date,
    pending_sessions: Iterable[Session] = (),
    *,
    subgroup_label: str | None = None,
    ignore_session_id: int | None = None,
) -> Iterable[Session]:
    target_label = _normalise_label(subgroup_label)

    for session in _course_sessions_in_week(
        course,
        week_start,
        week_end,
        pending_sessions,
        ignore_session_id=ignore_session_id,
    ):
        if not _session_involves_class(session, class_group):
            continue
        session_label = _normalise_label(session.subgroup_label)
        if session_label != target_label:
            continue
        yield session


def _course_class_hours_in_week(
    course: Course,
    class_group: ClassGroup,
    week_start: date,
    week_end: date,
    pending_sessions: Iterable[Session] = (),
    *,
    subgroup_label: str | None = None,
    ignore_session_id: int | None = None,
) -> int:
    return sum(
        session.duration_hours
        for session in _course_class_sessions_in_week(
            course,
            class_group,
            week_start,
            week_end,
            pending_sessions,
            subgroup_label=subgroup_label,
            ignore_session_id=ignore_session_id,
        )
    )


def has_weekly_course_conflict(
    course: Course,
    class_group: ClassGroup,
    start: datetime | date,
    *,
    subgroup_label: str | None = None,
    pending_sessions: Iterable[Session] = (),
    ignore_session_id: int | None = None,
    additional_hours: int | None = None,
) -> bool:
    return False


def _warn_weekly_limit(
    reporter: ScheduleReporter, weekly_conflicts: dict[str, Iterable[date]]
) -> None:
    if not weekly_conflicts:
        return
    for label, weeks in sorted(weekly_conflicts.items(), key=lambda item: item[0]):
        unique_weeks = sorted({week for week in weeks})
        if not unique_weeks:
            continue
        week_labels = [week.strftime("%d/%m/%Y") for week in unique_weeks]
        if len(week_labels) == 1:
            message = (
                "La durée hebdomadaire autorisée pour "
                f"{label} est déjà atteinte sur la semaine du {week_labels[0]}"
            )
        elif len(week_labels) == 2:
            message = (
                "La durée hebdomadaire autorisée pour "
                f"{label} est déjà atteinte sur les semaines du {week_labels[0]} "
                f"et du {week_labels[1]}"
            )
        elif len(week_labels) == 3:
            message = (
                "La durée hebdomadaire autorisée pour "
                f"{label} est déjà atteinte sur les semaines du {week_labels[0]}, "
                f"du {week_labels[1]} et du {week_labels[2]}"
            )
        else:
            message = (
                "La durée hebdomadaire autorisée pour "
                f"{label} est déjà atteinte sur les semaines du {week_labels[0]}, "
                f"du {week_labels[1]} et du {week_labels[2]}… "
                f"(+{len(week_labels) - 3} autre(s))"
            )
        reporter.warning(message)


def respects_weekly_chronology(
    course: Course,
    class_group: ClassGroup,
    start: datetime | date,
    *,
    subgroup_label: str | None = None,
    pending_sessions: Iterable[Session] = (),
    ignore_session_id: int | None = None,
) -> bool:
    is_datetime = isinstance(start, datetime)
    target_day = start.date() if is_datetime else start
    return _day_respects_chronology(
        course,
        class_group,
        target_day,
        pending_sessions,
        subgroup_label=subgroup_label,
        ignore_session_id=ignore_session_id,
        candidate_start=start if is_datetime else None,
    )


def _describe_class_unavailability(
    class_group: ClassGroup,
    start: datetime,
    end: datetime,
) -> str:
    start_label = start.strftime("%H:%M")
    end_label = end.strftime("%H:%M")
    return f"{class_group.name} est indisponible de {start_label} à {end_label}."


def find_available_teacher(
    course: Course,
    start: datetime,
    end: datetime,
    *,
    link: CourseClassLink | None = None,
    subgroup_label: str | None = None,
    segments: Optional[list[tuple[datetime, datetime]]] = None,
    target_class_ids: Set[int] | None = None,
) -> Optional[Teacher]:
    duration_hours = max((end - start).total_seconds() / 3600.0, 0.0)
    allocation_state = _get_allocation_state(course)
    preferred: list[Teacher] = []
    allowed_ids: set[int] | None = None
    if link is not None:
        for assigned in link.preferred_teachers(subgroup_label):
            if assigned is not None and assigned not in preferred:
                preferred.append(assigned)

    link_teachers = link.assigned_teachers() if link is not None else []
    course_teachers = [
        teacher for teacher in getattr(course, "teachers", []) if teacher is not None
    ]
    if link_teachers or course_teachers:
        fallback_pool = list(link_teachers)
        for teacher in course_teachers:
            if teacher not in fallback_pool:
                fallback_pool.append(teacher)
        allowed_ids = {
            teacher.id for teacher in fallback_pool if teacher.id is not None
        } or None
    else:
        fallback_pool = Teacher.query.all()

    def _append_unique(target: list[Teacher], items: Iterable[Teacher]) -> None:
        seen = {teacher.id for teacher in target if teacher.id is not None}
        for teacher in items:
            if teacher is None:
                continue
            teacher_id = teacher.id
            if allowed_ids is not None:
                if teacher_id is None or teacher_id not in allowed_ids:
                    continue
            if teacher_id is not None and teacher_id in seen:
                continue
            if allocation_state and not allocation_state.can_allocate(
                teacher_id, duration_hours
            ):
                continue
            target.append(teacher)
            if teacher_id is not None:
                seen.add(teacher_id)

    candidates: list[Teacher] = []
    if target_class_ids:
        target_label = _normalise_label(subgroup_label)
        existing_teachers: list[Teacher] = []
        seen_existing: set[int] = set()
        for session in sorted(
            course.sessions,
            key=lambda s: (s.start_time, s.id or 0),
        ):
            if session.teacher is None:
                continue
            if _session_attendee_ids(session) != target_class_ids:
                continue
            if _normalise_label(session.subgroup_label) != target_label:
                continue
            teacher = session.teacher
            if teacher.id is None:
                continue
            if teacher.id in seen_existing:
                continue
            existing_teachers.append(teacher)
            seen_existing.add(teacher.id)
        _append_unique(candidates, existing_teachers)

    _append_unique(candidates, preferred)
    if not candidates:
        _append_unique(
            candidates,
            sorted(
                [teacher for teacher in fallback_pool if teacher not in preferred],
                key=lambda t: t.name.lower(),
            ),
        )

    for teacher in candidates:
        segments_to_check = segments or [(start, end)]
        if not all(
            teacher.is_available_during(segment_start, segment_end)
            for segment_start, segment_end in segments_to_check
        ):
            continue
        if any(
            overlaps(s.start_time, s.end_time, segment_start, segment_end)
            for s in teacher.sessions
            for segment_start, segment_end in segments_to_check
        ):
            continue
        return teacher
    return None


def _normalise_label(label: str | None) -> str:
    return (label or "").upper()


def _week_start_for(day: date) -> date:
    return week_start_for(day)


def _class_hours_needed(
    course: Course,
    class_group: ClassGroup,
    subgroup_label: str | None = None,
    *,
    occurrences_goal: int | None = None,
) -> int:
    target_label = _normalise_label(subgroup_label)
    existing = sum(
        session.duration_hours
        for session in course.sessions
        if session.class_group_id == class_group.id
        and _normalise_label(session.subgroup_label) == target_label
    )
    target_occurrences = (
        occurrences_goal if occurrences_goal is not None else course.sessions_required
    )
    required_total = target_occurrences * course.session_length_hours
    return max(required_total - existing, 0)


def _existing_hours_by_day(
    course: Course, class_group: ClassGroup, subgroup_label: str | None = None
) -> dict[date, int]:
    target_label = _normalise_label(subgroup_label)
    per_day: dict[date, int] = {}
    for session in course.sessions:
        if session.class_group_id != class_group.id:
            continue
        if _normalise_label(session.subgroup_label) != target_label:
            continue
        session_day = session.start_time.date()
        per_day[session_day] = per_day.get(session_day, 0) + session.duration_hours
    return per_day


def _weekday_frequency_for_groups(
    course: Course,
    class_groups: Iterable[ClassGroup],
    *,
    pending_sessions: Iterable[Session] = (),
    subgroup_label: str | None = None,
) -> Counter[int]:
    groups = [group for group in class_groups if group is not None]
    if not groups:
        return Counter()
    target_label = _normalise_label(subgroup_label) if subgroup_label is not None else None
    weekday_counter: Counter[int] = Counter()
    seen: set[int] = set()
    candidates = list(course.sessions) + list(pending_sessions)
    for session in candidates:
        marker = id(session)
        if marker in seen:
            continue
        seen.add(marker)
        if session.course_id != course.id:
            continue
        if target_label is not None:
            session_label = _normalise_label(session.subgroup_label)
            if session_label and session_label != target_label:
                continue
        if not any(_session_involves_class(session, group) for group in groups):
            continue
        weekday_counter[session.start_time.weekday()] += 1
    return weekday_counter


def _preferred_slot_index_for_groups(
    course: Course,
    class_groups: Iterable[ClassGroup],
    day: date,
    *,
    pending_sessions: Iterable[Session] = (),
    subgroup_label: str | None = None,
) -> int | None:
    groups = [group for group in class_groups if group is not None]
    if not groups:
        return None
    target_weekday = day.weekday()
    target_label = _normalise_label(subgroup_label) if subgroup_label is not None else None
    slot_counter: Counter[int] = Counter()
    seen: set[int] = set()
    candidates = list(course.sessions) + list(pending_sessions)
    for session in candidates:
        marker = id(session)
        if marker in seen:
            continue
        seen.add(marker)
        if session.course_id != course.id:
            continue
        if session.start_time.weekday() != target_weekday:
            continue
        if target_label is not None:
            session_label = _normalise_label(session.subgroup_label)
            if session_label and session_label != target_label:
                continue
        if not any(_session_involves_class(session, group) for group in groups):
            continue
        try:
            slot_index = START_TIMES.index(session.start_time.time())
        except ValueError:
            continue
        slot_counter[slot_index] += 1
    if not slot_counter:
        return None
    ordered = sorted(slot_counter.items(), key=lambda item: (-item[1], item[0]))
    return ordered[0][0]


def _matching_sessions_for_groups(
    course: Course,
    class_groups: Iterable[ClassGroup],
    *,
    pending_sessions: Iterable[Session] = (),
    subgroup_label: str | None = None,
    require_exact_attendees: bool = False,
) -> list[Session]:
    groups = [group for group in class_groups if group is not None]
    if not groups:
        return []
    target_label = _normalise_label(subgroup_label) if subgroup_label is not None else None
    target_ids = {group.id for group in groups}
    seen: set[int] = set()
    matches: list[Session] = []
    candidates = list(course.sessions) + list(pending_sessions)
    for session in candidates:
        marker = id(session)
        if marker in seen:
            continue
        seen.add(marker)
        if session.course_id != course.id:
            continue
        if target_label is not None:
            session_label = _normalise_label(session.subgroup_label)
            if session_label and session_label != target_label:
                continue
        if require_exact_attendees:
            if session.attendee_ids() != target_ids:
                continue
        elif not any(_session_involves_class(session, group) for group in groups):
            continue
        matches.append(session)
    matches.sort(key=lambda s: s.start_time)
    return matches


def _relocate_sessions_for_groups(
    *,
    course: Course,
    class_groups: Iterable[ClassGroup],
    created_sessions: list[Session],
    per_day_hours: dict[date, int],
    weekday_frequencies: Counter[int],
    reporter: ScheduleReporter | None,
    attempted_weeks: set[date],
    subgroup_label: str | None = None,
    context_label: str | None = None,
    require_exact_attendees: bool = False,
) -> int:
    matches = _matching_sessions_for_groups(
        course,
        class_groups,
        pending_sessions=created_sessions,
        subgroup_label=subgroup_label,
        require_exact_attendees=require_exact_attendees,
    )
    if not matches:
        return 0

    sessions_by_week: dict[date, list[Session]] = defaultdict(list)
    for session in matches:
        week_start = _week_start_for(session.start_time.date())
        sessions_by_week[week_start].append(session)

    for week_start in sorted(sessions_by_week.keys(), reverse=True):
        if week_start in attempted_weeks:
            continue
        targeted = sessions_by_week[week_start]
        if not targeted:
            continue

        attempted_weeks.add(week_start)
        total_hours = 0
        for session in targeted:
            total_hours += session.duration_hours
            if session in created_sessions:
                created_sessions.remove(session)
            session_day = session.start_time.date()
            if session_day in per_day_hours:
                per_day_hours[session_day] = max(
                    per_day_hours[session_day] - session.duration_hours,
                    0,
                )
            weekday = session.start_time.weekday()
            if weekday in weekday_frequencies:
                weekday_frequencies[weekday] -= 1
                if weekday_frequencies[weekday] <= 0:
                    del weekday_frequencies[weekday]
            db.session.delete(session)
        db.session.flush()

        if reporter is not None:
            context = context_label or course.name
            reporter.info(
                "Replanification des séances de la semaine du "
                f"{week_start.strftime('%d/%m/%Y')} pour {context}."
            )
        return total_hours
    return 0


def _latest_session_for_groups(
    course: Course,
    class_groups: Iterable[ClassGroup],
    *,
    pending_sessions: Iterable[Session] = (),
    subgroup_label: str | None = None,
    require_exact_attendees: bool = False,
) -> Session | None:
    matches = _matching_sessions_for_groups(
        course,
        class_groups,
        pending_sessions=pending_sessions,
        subgroup_label=subgroup_label,
        require_exact_attendees=require_exact_attendees,
    )
    return matches[-1] if matches else None


def _collect_contiguous_slots(start_index: int, length: int) -> list[tuple[time, time]] | None:
    return collect_contiguous_slots(start_index, length)


def _slots_are_adjacent(first_index: int, second_index: int) -> bool:
    if first_index == second_index:
        return False
    lower, upper = sorted((first_index, second_index))
    lower_end = SCHEDULE_SLOTS[lower][1]
    upper_start = SCHEDULE_SLOTS[upper][0]
    return lower_end == upper_start


def _report_one_hour_alignment(
    *,
    course: Course,
    class_group: ClassGroup | None,
    reporter: ScheduleReporter | None,
    pending_sessions: Iterable[Session] = (),
    link: CourseClassLink | None = None,
    subgroup_label: str | None = None,
) -> None:
    if reporter is None or class_group is None:
        return

    sessions = _matching_sessions_for_groups(
        course,
        [class_group],
        pending_sessions=pending_sessions,
        subgroup_label=subgroup_label,
    )
    by_day: dict[date, list[Session]] = defaultdict(list)
    for session in sessions:
        if session.start_time is None or session.duration_hours != 1:
            continue
        by_day[session.start_time.date()].append(session)

    for day, day_sessions in by_day.items():
        if len(day_sessions) <= 1:
            continue
        ordered = sorted(day_sessions, key=lambda s: (s.start_time, s.id or 0))
        violation_detected = False
        for earlier, later in zip(ordered, ordered[1:]):
            if later.start_time != earlier.end_time:
                violation_detected = True
                break
        if not violation_detected:
            continue
        label = format_class_label(
            class_group, link=link, subgroup_label=subgroup_label
        )
        reporter.warning(
            "Séances d'1 h non consécutives détectées pour "
            f"{course.name} — {label} le {day.strftime('%d/%m/%Y')}"
        )


def _one_hour_adjacency_offsets(
    class_groups: Iterable[ClassGroup],
    day: date,
    *,
    pending_sessions: Iterable[Session] = (),
    subgroup_label: str | None = None,
) -> list[int]:
    offsets: list[int] = []
    seen_offsets: set[int] = set()

    for group in class_groups:
        if group is None:
            continue
        day_sessions = _class_sessions_on_day(
            group,
            day,
            pending_sessions=pending_sessions,
            subgroup_label=subgroup_label,
        )
        occupied_indices: set[int] = set()
        for session in day_sessions:
            try:
                slot_index = START_TIMES.index(session.start_time.time())
            except (AttributeError, ValueError):
                continue
            occupied_indices.add(slot_index)
        for session in day_sessions:
            if session.duration_hours != 1:
                continue
            try:
                session_slot = START_TIMES.index(session.start_time.time())
            except ValueError:
                continue
            for neighbour in (session_slot - 1, session_slot + 1):
                if neighbour < 0 or neighbour >= len(SCHEDULE_SLOTS):
                    continue
                if neighbour in seen_offsets or neighbour in occupied_indices:
                    continue
                if not _slots_are_adjacent(session_slot, neighbour):
                    continue
                offsets.append(neighbour)
                seen_offsets.add(neighbour)

    return offsets


def _schedule_block_for_day(
    *,
    course: Course,
    class_group: ClassGroup,
    link: CourseClassLink,
    subgroup_label: str | None,
    day: date,
    desired_hours: int,
    base_offset: int,
    pending_sessions: Iterable[Session] = (),
    reporter: ScheduleReporter | None = None,
) -> list[Session] | None:
    diagnostics = PlacementDiagnostics()
    context = class_group.name
    if subgroup_label:
        context += f" — groupe {subgroup_label.upper()}"
    placement = _try_full_block(
        course=course,
        class_group=class_group,
        link=link,
        subgroup_label=subgroup_label,
        day=day,
        desired_hours=desired_hours,
        base_offset=base_offset,
        pending_sessions=pending_sessions,
        diagnostics=diagnostics,
    )
    if placement:
        return placement
    if desired_hours <= 1:
        diagnostics.emit(
            reporter,
            context_label=context,
            day=day,
        )
        return None
    placement = _try_split_block(
        course=course,
        class_group=class_group,
        link=link,
        subgroup_label=subgroup_label,
        day=day,
        desired_hours=desired_hours,
        base_offset=base_offset,
        pending_sessions=pending_sessions,
        diagnostics=diagnostics,
    )
    if placement:
        return placement
    diagnostics.emit(
        reporter,
        context_label=context,
        day=day,
    )
    return None


def _try_full_block(
    *,
    course: Course,
    class_group: ClassGroup,
    link: CourseClassLink,
    subgroup_label: str | None,
    day: date,
    desired_hours: int,
    base_offset: int,
    pending_sessions: Iterable[Session] = (),
    diagnostics: PlacementDiagnostics | None = None,
) -> list[Session] | None:
    required_capacity = course.capacity_needed_for(class_group)
    target_class_ids = (
        {class_group.id} if class_group.id is not None else set()
    )
    for offset in range(len(START_TIMES)):
        slot_index = (base_offset + offset) % len(START_TIMES)
        slot_start_time = START_TIMES[slot_index]
        start_dt = datetime.combine(day, slot_start_time)
        end_dt = start_dt + timedelta(hours=desired_hours)
        if not fits_in_windows(start_dt.time(), end_dt.time()):
            continue
        if not class_group.is_available_during(
            start_dt, end_dt, subgroup_label=subgroup_label
        ):
            if diagnostics is not None:
                diagnostics.add_class(
                    _describe_class_unavailability(class_group, start_dt, end_dt)
                )
            continue
        teacher = find_available_teacher(
            course,
            start_dt,
            end_dt,
            link=link,
            subgroup_label=subgroup_label,
            target_class_ids=target_class_ids or None,
        )
        if not teacher:
            if diagnostics is not None:
                diagnostics.add_teacher(
                    _describe_teacher_unavailability(
                        course,
                        start_dt,
                        end_dt,
                        link=link,
                        subgroup_label=subgroup_label,
                    )
                )
            continue
        room = find_available_room(
            course,
            start_dt,
            end_dt,
            required_capacity=required_capacity,
        )
        if not room:
            if diagnostics is not None:
                diagnostics.add_room(
                    _describe_room_unavailability(
                        course,
                        start_dt,
                        end_dt,
                        required_capacity=required_capacity,
                    )
                )
            continue
        if not _day_respects_chronology(
            course,
            class_group,
            day,
            pending_sessions,
            subgroup_label=subgroup_label,
            candidate_start=start_dt,
        ):
            if diagnostics is not None:
                diagnostics.add_other(
                    "La chronologie CM → TD → TP → Eval serait violée sur ce créneau."
                )
            continue
        session = Session(
            course=course,
            teacher=teacher,
            room=room,
            class_group=class_group,
            subgroup_label=subgroup_label,
            start_time=start_dt,
            end_time=end_dt,
        )
        session.attendees = [class_group]
        db.session.add(session)
        # Certains connecteurs MariaDB présentent un bug avec les insertions en
        # lot exécutées via ``executemany`` et lèvent une ``SystemError`` sans
        # message.  En vidant la session SQLAlchemy dès la création, chaque
        # séance est insérée individuellement et on évite le chemin fautif.
        db.session.flush()
        return [session]
    return None


def _try_split_block(
    *,
    course: Course,
    class_group: ClassGroup,
    link: CourseClassLink,
    subgroup_label: str | None,
    day: date,
    desired_hours: int,
    base_offset: int,
    pending_sessions: Iterable[Session] = (),
    diagnostics: PlacementDiagnostics | None = None,
) -> list[Session] | None:
    segment_lengths = [2, 2] if desired_hours == 4 else [1] * desired_hours
    segment_count = sum(segment_lengths)
    required_capacity = course.capacity_needed_for(class_group)
    target_class_ids = (
        {class_group.id} if class_group.id is not None else set()
    )
    slot_count = len(SCHEDULE_SLOTS)
    for offset in range(slot_count):
        start_index = (base_offset + offset) % slot_count
        contiguous = _collect_contiguous_slots(start_index, segment_count)
        if not contiguous:
            continue
        if not all(fits_in_windows(start, end) for start, end in contiguous):
            continue
        segment_datetimes: list[tuple[datetime, datetime]] = []
        index = 0
        for length in segment_lengths:
            segment_start = contiguous[index][0]
            segment_end = contiguous[index + length - 1][1]
            segment_datetimes.append(
                (
                    datetime.combine(day, segment_start),
                    datetime.combine(day, segment_end),
                )
            )
            index += length
        start_dt = segment_datetimes[0][0]
        end_dt = segment_datetimes[-1][1]
        if not all(
            class_group.is_available_during(
                segment_start,
                segment_end,
                subgroup_label=subgroup_label,
            )
            for segment_start, segment_end in segment_datetimes
        ):
            if diagnostics is not None:
                for segment_start, segment_end in segment_datetimes:
                    if not class_group.is_available_during(
                        segment_start,
                        segment_end,
                        subgroup_label=subgroup_label,
                    ):
                        diagnostics.add_class(
                            _describe_class_unavailability(
                                class_group,
                                segment_start,
                                segment_end,
                            )
                        )
            continue
        teacher = find_available_teacher(
            course,
            start_dt,
            end_dt,
            link=link,
            subgroup_label=subgroup_label,
            segments=segment_datetimes,
            target_class_ids=target_class_ids or None,
        )
        if not teacher:
            if diagnostics is not None:
                diagnostics.add_teacher(
                    _describe_teacher_unavailability(
                        course,
                        start_dt,
                        end_dt,
                        link=link,
                        subgroup_label=subgroup_label,
                        segments=segment_datetimes,
                    )
                )
            continue
        rooms: list[Room] = []
        valid = True
        for seg_start, seg_end in segment_datetimes:
            if any(
                overlaps(existing.start_time, existing.end_time, seg_start, seg_end)
                for existing in teacher.sessions
            ):
                if diagnostics is not None:
                    diagnostics.add_teacher(
                        f"{teacher.name} est déjà planifié sur {seg_start.strftime('%d/%m %H:%M')}"
                    )
                valid = False
                break
            room = find_available_room(
                course,
                seg_start,
                seg_end,
                required_capacity=required_capacity,
            )
            if not room:
                if diagnostics is not None:
                    diagnostics.add_room(
                        _describe_room_unavailability(
                            course,
                            seg_start,
                            seg_end,
                            required_capacity=required_capacity,
                        )
                    )
                valid = False
                break
            rooms.append(room)
        if not valid:
            continue
        if not _day_respects_chronology(
            course,
            class_group,
            day,
            pending_sessions,
            subgroup_label=subgroup_label,
            candidate_start=start_dt,
        ):
            if diagnostics is not None:
                diagnostics.add_other(
                    "La chronologie CM → TD → TP → Eval serait violée sur ce créneau."
                )
            continue
        sessions: list[Session] = []
        for idx, (seg_start, seg_end) in enumerate(segment_datetimes):
            session = Session(
                course=course,
                teacher=teacher,
                room=rooms[idx],
                class_group=class_group,
                subgroup_label=subgroup_label,
                start_time=seg_start,
                end_time=seg_end,
            )
            session.attendees = [class_group]
            db.session.add(session)
            db.session.flush()
            sessions.append(session)
        return sessions
    return None


def _session_attendee_ids(session: Session) -> Set[int]:
    ids = session.attendee_ids()
    if ids:
        return ids
    if session.class_group_id:
        return {session.class_group_id}
    return set()


def _cm_existing_hours_by_day(course: Course, target_ids: Set[int]) -> dict[date, int]:
    per_day: dict[date, int] = {}
    for session in course.sessions:
        if _session_attendee_ids(session) != target_ids:
            continue
        session_day = session.start_time.date()
        per_day[session_day] = per_day.get(session_day, 0) + session.duration_hours
    return per_day


def _cm_schedule_block_for_day(
    *,
    course: Course,
    class_groups: list[ClassGroup],
    primary_link: CourseClassLink | None,
    day: date,
    desired_hours: int,
    base_offset: int,
    pending_sessions: Iterable[Session] = (),
    reporter: ScheduleReporter | None = None,
) -> list[Session] | None:
    diagnostics = PlacementDiagnostics()
    context = ", ".join(group.name for group in class_groups) or course.name
    placement = _cm_try_full_block(
        course=course,
        class_groups=class_groups,
        primary_link=primary_link,
        day=day,
        desired_hours=desired_hours,
        base_offset=base_offset,
        pending_sessions=pending_sessions,
        diagnostics=diagnostics,
    )
    if placement:
        return placement
    if desired_hours <= 1:
        diagnostics.emit(
            reporter,
            context_label=context,
            day=day,
        )
        return None
    placement = _cm_try_split_block(
        course=course,
        class_groups=class_groups,
        primary_link=primary_link,
        day=day,
        desired_hours=desired_hours,
        base_offset=base_offset,
        pending_sessions=pending_sessions,
        diagnostics=diagnostics,
    )
    if placement:
        return placement
    diagnostics.emit(
        reporter,
        context_label=context,
        day=day,
    )
    return None


def _cm_try_full_block(
    *,
    course: Course,
    class_groups: list[ClassGroup],
    primary_link: CourseClassLink | None,
    day: date,
    desired_hours: int,
    base_offset: int,
    pending_sessions: Iterable[Session] = (),
    diagnostics: PlacementDiagnostics | None = None,
) -> list[Session] | None:
    if not class_groups:
        return None
    required_capacity = sum(course.capacity_needed_for(group) for group in class_groups)
    primary_class = class_groups[0]
    target_class_ids = {
        group.id for group in class_groups if group is not None and group.id is not None
    }
    for offset in range(len(START_TIMES)):
        slot_index = (base_offset + offset) % len(START_TIMES)
        slot_start_time = START_TIMES[slot_index]
        start_dt = datetime.combine(day, slot_start_time)
        end_dt = start_dt + timedelta(hours=desired_hours)
        if not fits_in_windows(start_dt.time(), end_dt.time()):
            continue
        unavailable_groups = [
            class_group
            for class_group in class_groups
            if not class_group.is_available_during(start_dt, end_dt)
        ]
        if unavailable_groups:
            if diagnostics is not None:
                for group in unavailable_groups:
                    diagnostics.add_class(
                        _describe_class_unavailability(group, start_dt, end_dt)
                    )
            continue
        teacher = find_available_teacher(
            course,
            start_dt,
            end_dt,
            link=primary_link,
            subgroup_label=None,
            target_class_ids=target_class_ids or None,
        )
        if not teacher:
            if diagnostics is not None:
                diagnostics.add_teacher(
                    _describe_teacher_unavailability(
                        course,
                        start_dt,
                        end_dt,
                        link=primary_link,
                        subgroup_label=None,
                    )
                )
            continue
        room = find_available_room(
            course,
            start_dt,
            end_dt,
            required_capacity=required_capacity,
        )
        if not room:
            if diagnostics is not None:
                diagnostics.add_room(
                    _describe_room_unavailability(
                        course,
                        start_dt,
                        end_dt,
                        required_capacity=required_capacity,
                    )
                )
            continue
        chronology_ok = True
        for group in class_groups:
            if not _day_respects_chronology(
                course,
                group,
                day,
                pending_sessions,
                subgroup_label=None,
                candidate_start=start_dt,
            ):
                chronology_ok = False
                break
        if not chronology_ok:
            if diagnostics is not None:
                diagnostics.add_other(
                    "La chronologie CM → TD → TP → Eval serait violée sur ce créneau."
                )
            continue
        session = Session(
            course=course,
            teacher=teacher,
            room=room,
            class_group=primary_class,
            start_time=start_dt,
            end_time=end_dt,
        )
        session.attendees = list(class_groups)
        db.session.add(session)
        db.session.flush()
        return [session]
    return None


def _cm_try_split_block(
    *,
    course: Course,
    class_groups: list[ClassGroup],
    primary_link: CourseClassLink | None,
    day: date,
    desired_hours: int,
    base_offset: int,
    pending_sessions: Iterable[Session] = (),
    diagnostics: PlacementDiagnostics | None = None,
) -> list[Session] | None:
    if not class_groups:
        return None
    segment_lengths = [2, 2] if desired_hours == 4 else [1] * desired_hours
    segment_count = sum(segment_lengths)
    required_capacity = sum(course.capacity_needed_for(group) for group in class_groups)
    slot_count = len(SCHEDULE_SLOTS)
    primary_class = class_groups[0]
    target_class_ids = {
        group.id for group in class_groups if group is not None and group.id is not None
    }
    for offset in range(slot_count):
        start_index = (base_offset + offset) % slot_count
        contiguous = _collect_contiguous_slots(start_index, segment_count)
        if not contiguous:
            continue
        if not all(fits_in_windows(start, end) for start, end in contiguous):
            continue
        segment_datetimes: list[tuple[datetime, datetime]] = []
        index = 0
        for length in segment_lengths:
            segment_start = contiguous[index][0]
            segment_end = contiguous[index + length - 1][1]
            segment_datetimes.append(
                (
                    datetime.combine(day, segment_start),
                    datetime.combine(day, segment_end),
                )
            )
            index += length
        availability_blocks = []
        for class_group in class_groups:
            for segment_start, segment_end in segment_datetimes:
                if not class_group.is_available_during(segment_start, segment_end):
                    availability_blocks.append((class_group, segment_start, segment_end))
        if availability_blocks:
            if diagnostics is not None:
                for group, segment_start, segment_end in availability_blocks:
                    diagnostics.add_class(
                        _describe_class_unavailability(group, segment_start, segment_end)
                    )
            continue
        teacher = find_available_teacher(
            course,
            segment_datetimes[0][0],
            segment_datetimes[-1][1],
            link=primary_link,
            subgroup_label=None,
            segments=segment_datetimes,
            target_class_ids=target_class_ids or None,
        )
        if not teacher:
            if diagnostics is not None:
                diagnostics.add_teacher(
                    _describe_teacher_unavailability(
                        course,
                        segment_datetimes[0][0],
                        segment_datetimes[-1][1],
                        link=primary_link,
                        subgroup_label=None,
                        segments=segment_datetimes,
                    )
                )
            continue
        rooms: list[Room] = []
        valid = True
        for seg_start, seg_end in segment_datetimes:
            if any(
                overlaps(existing.start_time, existing.end_time, seg_start, seg_end)
                for existing in teacher.sessions
            ):
                if diagnostics is not None:
                    diagnostics.add_teacher(
                        f"{teacher.name} est déjà planifié sur {seg_start.strftime('%d/%m %H:%M')}"
                    )
                valid = False
                break
            room = find_available_room(
                course,
                seg_start,
                seg_end,
                required_capacity=required_capacity,
            )
            if not room:
                if diagnostics is not None:
                    diagnostics.add_room(
                        _describe_room_unavailability(
                            course,
                            seg_start,
                            seg_end,
                            required_capacity=required_capacity,
                        )
                    )
                valid = False
                break
            rooms.append(room)
        if not valid:
            continue
        chronology_ok = True
        candidate_start = segment_datetimes[0][0]
        for group in class_groups:
            if not _day_respects_chronology(
                course,
                group,
                day,
                pending_sessions,
                subgroup_label=None,
                candidate_start=candidate_start,
            ):
                chronology_ok = False
                break
        if not chronology_ok:
            if diagnostics is not None:
                diagnostics.add_other(
                    "La chronologie CM → TD → TP → Eval serait violée sur ce créneau."
                )
            continue
        sessions: list[Session] = []
        for idx, (seg_start, seg_end) in enumerate(segment_datetimes):
            session = Session(
                course=course,
                teacher=teacher,
                room=rooms[idx],
                class_group=primary_class,
                start_time=seg_start,
                end_time=seg_end,
            )
            session.attendees = list(class_groups)
            db.session.add(session)
            db.session.flush()
            sessions.append(session)
        return sessions
    return None


def _resolve_schedule_window(
    course: Course, window_start: date | None, window_end: date | None
) -> tuple[date, date]:
    semester_window = course.semester_window
    start_candidates: list[date] = []
    end_candidates: list[date] = []
    if semester_window is not None:
        start_candidates.append(semester_window[0])
        end_candidates.append(semester_window[1])
    if window_start is not None:
        start_candidates.append(window_start)
    if window_end is not None:
        end_candidates.append(window_end)
    if not start_candidates or not end_candidates:
        raise ValueError(
            "Aucune période de planification n'est définie pour ce semestre."
        )
    start = max(start_candidates)
    end = min(end_candidates)
    if start > end:
        raise ValueError(
            "La période choisie n'intersecte pas la fenêtre du semestre."
        )
    return start, end


def generate_schedule(
    course: Course,
    *,
    window_start: date | None = None,
    window_end: date | None = None,
    allowed_weeks: Iterable[tuple[date, date]] | None = None,
    progress: ScheduleProgress | None = None,
) -> list[Session]:
    from app.planning.generator import generate_schedule as planning_generate_schedule

    return planning_generate_schedule(
        course,
        window_start=window_start,
        window_end=window_end,
        allowed_weeks=allowed_weeks,
        progress=progress or NullScheduleProgress(),
    )
