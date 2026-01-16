from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Protocol

from app.models import ClassGroup, Course, CourseClassLink, Room, Session, Teacher
from app.planning.utils import overlaps, week_bounds


class SessionLike(Protocol):
    start_time: object
    end_time: object
    teacher_id: int | None
    room_id: int | None
    class_group_id: int | None
    subgroup_label: str | None
    attendees: list[ClassGroup] | None


class ReasonCode(str, Enum):
    CLASS_UNAVAILABLE = "class_unavailable"
    CLASS_CONFLICT = "class_conflict"
    TEACHER_UNAVAILABLE = "teacher_unavailable"
    TEACHER_CONFLICT = "teacher_conflict"
    TEACHER_ALLOCATION = "teacher_allocation"
    ROOM_CAPACITY = "room_capacity"
    ROOM_COMPUTERS = "room_computers"
    ROOM_EQUIPMENT = "room_equipment"
    ROOM_SOFTWARE = "room_software"
    ROOM_CONFLICT = "room_conflict"
    ROOM_UNAVAILABLE = "room_unavailable"
    CHRONOLOGY = "chronology"
    WEEKLY_LIMIT = "weekly_limit"


@dataclass(frozen=True)
class ConstraintViolation:
    code: ReasonCode
    message: str


@dataclass(frozen=True)
class SessionRequest:
    course: Course
    class_groups: list[ClassGroup]
    subgroup_label: str | None
    duration_hours: int
    link: CourseClassLink | None
    primary_link: CourseClassLink | None

    @property
    def primary_class(self) -> ClassGroup | None:
        return self.class_groups[0] if self.class_groups else None


def _session_involves_class(session: SessionLike, class_group: ClassGroup) -> bool:
    if session.class_group_id == class_group.id:
        return True
    attendees = session.attendees or []
    return any(att.id == class_group.id for att in attendees)


def _normalise_label(label: str | None) -> str:
    return (label or "").upper()


def _course_type_priority(course_type: str | None) -> int | None:
    if not course_type:
        return None
    chronology = {"CM": 0, "TD": 1, "TP": 2, "TEST": 3, "EVAL": 3, "Eval": 3}
    priority = chronology.get(course_type)
    if priority is not None:
        return priority
    return chronology.get(course_type.upper())


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


def respects_weekly_chronology(
    course: Course,
    class_group: ClassGroup,
    start,
    *,
    subgroup_label: str | None = None,
    pending_sessions: Iterable[SessionLike] = (),
    candidate_start=None,
) -> bool:
    priority = _course_type_priority(course.course_type)
    if priority is None:
        return True
    family_key = _course_family_key(course)
    semester = family_key[2]
    target_label = _normalise_label(subgroup_label) if subgroup_label is not None else None

    def _iter_sessions() -> Iterable[SessionLike]:
        seen: set[int] = set()
        collections = [class_group.all_sessions]
        collections.append(list(pending_sessions))
        for collection in collections:
            for session in collection:
                marker = getattr(session, "id", None) or id(session)
                if marker in seen:
                    continue
                seen.add(marker)
                yield session

    week_start, week_end = week_bounds(start.date() if hasattr(start, "date") else start)
    candidate_day = (
        candidate_start.date() if hasattr(candidate_start, "date") else start
    )

    for session in _iter_sessions():
        if not _session_involves_class(session, class_group):
            continue
        if target_label is not None:
            session_label = _normalise_label(getattr(session, "subgroup_label", None))
            if session_label and session_label != target_label:
                continue
        other_course = getattr(session, "course", None)
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
        if other_priority < priority and session_day > start:
            return False
        if other_priority > priority and session_day < start:
            return False
    return True


def available_teachers(
    course: Course,
    *,
    link: CourseClassLink | None,
    subgroup_label: str | None,
    allocation_state=None,
    target_class_ids: set[int] | None = None,
) -> list[Teacher]:
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
                teacher_id, 0.0
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
            attendee_ids = session.attendee_ids()
            if attendee_ids != target_class_ids:
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
    _append_unique(
        candidates,
        sorted(
            [teacher for teacher in fallback_pool if teacher not in preferred],
            key=lambda t: t.name.lower(),
        ),
    )
    return candidates


def ordered_rooms(course: Course) -> list[Room]:
    rooms = Room.query.order_by(Room.capacity.asc(), Room.name.asc()).all()
    preferred_rooms: list[Room] = []
    preferred_room_ids: set[int] = set()
    if course.preferred_rooms:
        preferred_rooms = sorted(
            [room for room in course.preferred_rooms if room is not None],
            key=lambda room: (room.capacity or 0, (room.name or "").lower()),
        )
        preferred_room_ids = {room.id for room in preferred_rooms if room.id}
    ordered: list[Room] = []
    ordered.extend(preferred_rooms)
    ordered.extend(room for room in rooms if room.id not in preferred_room_ids)
    return ordered


def can_place(
    request: SessionRequest,
    *,
    teacher: Teacher,
    rooms: list[Room],
    segments: list[tuple],
    pending_sessions: Iterable[SessionLike] = (),
    allocation_state=None,
    weekly_targets: dict | None = None,
) -> list[ConstraintViolation]:
    violations: list[ConstraintViolation] = []
    duration_hours = request.duration_hours

    for class_group in request.class_groups:
        for start, end in segments:
            if not class_group.is_available_during(
                start, end, subgroup_label=request.subgroup_label
            ):
                violations.append(
                    ConstraintViolation(
                        ReasonCode.CLASS_UNAVAILABLE,
                        f"{class_group.name} indisponible sur ce créneau.",
                    )
                )
                break
            conflict = any(
                _session_involves_class(session, class_group)
                and overlaps(session.start_time, session.end_time, start, end)
                for session in pending_sessions
            )
            if conflict:
                violations.append(
                    ConstraintViolation(
                        ReasonCode.CLASS_CONFLICT,
                        f"{class_group.name} déjà planifiée sur ce créneau.",
                    )
                )
                break

    if not all(
        teacher.is_available_during(start, end) for start, end in segments
    ):
        violations.append(
            ConstraintViolation(
                ReasonCode.TEACHER_UNAVAILABLE,
                f"{teacher.name} indisponible sur ce créneau.",
            )
        )
    conflict = any(
        teacher.id
        and session.teacher_id == teacher.id
        and overlaps(session.start_time, session.end_time, start, end)
        for session in pending_sessions
        for start, end in segments
    )
    if not conflict:
        conflict = any(
            overlaps(existing.start_time, existing.end_time, start, end)
            for existing in teacher.sessions
            for start, end in segments
        )
    if conflict:
        violations.append(
            ConstraintViolation(
                ReasonCode.TEACHER_CONFLICT,
                f"{teacher.name} déjà planifié sur ce créneau.",
            )
        )
    if allocation_state and not allocation_state.can_allocate(teacher.id, float(duration_hours)):
        violations.append(
            ConstraintViolation(
                ReasonCode.TEACHER_ALLOCATION,
                f"{teacher.name} dépasse son quota d'heures.",
            )
        )

    required_students = max(
        sum(request.course.capacity_needed_for(group) for group in request.class_groups),
        1,
    )
    required_posts = request.course.required_computer_posts()
    required_equipment_ids = {equipment.id for equipment in request.course.equipments}
    required_software_ids = {software.id for software in request.course.softwares}

    for room in rooms:
        if room.capacity < required_students:
            violations.append(
                ConstraintViolation(
                    ReasonCode.ROOM_CAPACITY,
                    f"{room.name} trop petite pour la capacité requise.",
                )
            )
            continue
        if required_posts and (room.computers or 0) < required_posts:
            violations.append(
                ConstraintViolation(
                    ReasonCode.ROOM_COMPUTERS,
                    f"{room.name} manque de postes informatiques.",
                )
            )
            continue
        room_equipment_ids = {equipment.id for equipment in room.equipments}
        if required_equipment_ids.difference(room_equipment_ids):
            violations.append(
                ConstraintViolation(
                    ReasonCode.ROOM_EQUIPMENT,
                    f"{room.name} ne dispose pas des équipements requis.",
                )
            )
            continue
        room_software_ids = {software.id for software in room.softwares}
        if required_software_ids.difference(room_software_ids):
            violations.append(
                ConstraintViolation(
                    ReasonCode.ROOM_SOFTWARE,
                    f"{room.name} ne dispose pas des logiciels requis.",
                )
            )
            continue
        conflict = any(
            room.id
            and session.room_id == room.id
            and overlaps(session.start_time, session.end_time, start, end)
            for session in pending_sessions
            for start, end in segments
        )
        if not conflict:
            conflict = any(
                overlaps(existing.start_time, existing.end_time, start, end)
                for existing in room.sessions
                for start, end in segments
            )
        if conflict:
            violations.append(
                ConstraintViolation(
                    ReasonCode.ROOM_CONFLICT,
                    f"{room.name} occupée sur ce créneau.",
                )
            )
            continue

    for class_group in request.class_groups:
        if not respects_weekly_chronology(
            request.course,
            class_group,
            segments[0][0],
            subgroup_label=request.subgroup_label,
            pending_sessions=pending_sessions,
            candidate_start=segments[0][0],
        ):
            violations.append(
                ConstraintViolation(
                    ReasonCode.CHRONOLOGY,
                    "Chronologie CM → TD → TP → Eval non respectée.",
                )
            )
            break

    if weekly_targets:
        week_start, _ = week_bounds(segments[0][0].date())
        weekly_goal = weekly_targets.get(week_start)
        if weekly_goal is not None:
            weekly_limit_hours = max(int(weekly_goal), 0) * max(
                int(request.course.session_length_hours or 1), 1
            )
            current_hours = 0
            for session in request.course.sessions:
                session_week_start, _ = week_bounds(session.start_time.date())
                if session_week_start != week_start:
                    continue
                if request.class_groups and not any(
                    _session_involves_class(session, group)
                    for group in request.class_groups
                ):
                    continue
                current_hours += session.duration_hours
            for session in pending_sessions:
                if getattr(session, "course", None) != request.course and getattr(
                    session, "course_id", None
                ) != request.course.id:
                    continue
                session_week_start, _ = week_bounds(session.start_time.date())
                if session_week_start != week_start:
                    continue
                if request.class_groups and not any(
                    _session_involves_class(session, group)
                    for group in request.class_groups
                ):
                    continue
                current_hours += getattr(session, "duration_hours", 0)
            if current_hours + duration_hours > weekly_limit_hours:
                violations.append(
                    ConstraintViolation(
                        ReasonCode.WEEKLY_LIMIT,
                        "Durée hebdomadaire autorisée dépassée.",
                    )
                )

    return violations
