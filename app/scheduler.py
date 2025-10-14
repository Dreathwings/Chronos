from __future__ import annotations

import json
import logging
from datetime import date, datetime, time, timedelta
from typing import Iterable, List, Optional, Set

from flask import current_app

from . import db
from .models import (
    ClassGroup,
    Course,
    CourseClassLink,
    CourseScheduleLog,
    Room,
    Session,
    Teacher,
)

# Working windows respecting pauses
WORKING_WINDOWS: List[tuple[time, time]] = [
    (time(8, 0), time(10, 0)),
    (time(10, 15), time(12, 15)),
    (time(13, 30), time(15, 30)),
    (time(15, 45), time(17, 45)),
]

SCHEDULE_SLOTS: List[tuple[time, time]] = [
    (time(8, 0), time(9, 0)),
    (time(9, 0), time(10, 0)),
    (time(10, 15), time(11, 15)),
    (time(11, 15), time(12, 15)),
    (time(13, 30), time(14, 30)),
    (time(14, 30), time(15, 30)),
    (time(15, 45), time(16, 45)),
    (time(16, 45), time(17, 45)),
]

MAX_SLOT_GAP = timedelta(minutes=15)


def _build_extended_breaks() -> set[tuple[time, time]]:
    extended: set[tuple[time, time]] = set()
    for idx in range(len(WORKING_WINDOWS) - 1):
        _, current_end = WORKING_WINDOWS[idx]
        next_start, _ = WORKING_WINDOWS[idx + 1]
        gap = datetime.combine(date.min, next_start) - datetime.combine(
            date.min, current_end
        )
        if gap > MAX_SLOT_GAP:
            extended.add((current_end, next_start))
    return extended


EXTENDED_BREAKS = _build_extended_breaks()

START_TIMES: List[time] = [slot_start for slot_start, _ in SCHEDULE_SLOTS]


class ScheduleReporter:
    LEVELS = {
        "info": logging.INFO,
        "warning": logging.WARNING,
        "error": logging.ERROR,
    }

    def __init__(
        self,
        course: Course,
        *,
        window_start: date | None = None,
        window_end: date | None = None,
    ) -> None:
        self.course = course
        self.window_start = window_start
        self.window_end = window_end
        self.entries: list[dict[str, str]] = []
        self.status = "success"
        self.summary: str | None = None
        self._finalised = False
        self._record: CourseScheduleLog | None = None

    def set_window(self, start: date, end: date) -> None:
        self.window_start = start
        self.window_end = end
        self.info(f"Fenêtre de planification : {start} → {end}")

    def info(self, message: str) -> None:
        self._add_entry("info", message)

    def warning(self, message: str) -> None:
        self._add_entry("warning", message)
        if self.status != "error":
            self.status = "warning"

    def error(self, message: str) -> None:
        self._add_entry("error", message)
        self.status = "error"

    def session_created(self, session: Session) -> None:
        start_label = session.start_time.strftime("%d/%m/%Y %H:%M")
        end_label = session.end_time.strftime("%H:%M")
        attendees = ", ".join(session.attendee_names())
        teacher_name = session.teacher.name if session.teacher else "Aucun enseignant"
        room_name = session.room.name if session.room else "Aucune salle"
        duration = session.duration_hours
        self.info(
            f"Séance planifiée le {start_label} → {end_label} ({duration} h)"
            f" — {attendees} avec {teacher_name} en salle {room_name}"
        )

    def finalise(self, created_count: int) -> CourseScheduleLog:
        if self._finalised and self._record is not None:
            return self._record
        if self.summary is None:
            if created_count:
                if self.status == "success":
                    self.summary = f"{created_count} séance(s) générée(s)"
                else:
                    self.summary = (
                        f"{created_count} séance(s) générée(s) avec avertissements"
                    )
            else:
                if self.status == "success":
                    self.summary = "Aucune séance générée"
                else:
                    self.summary = "Aucune séance générée — vérifier les avertissements"

        log = CourseScheduleLog(
            course=self.course,
            status=self.status,
            summary=self.summary,
            messages=json.dumps(self.entries, ensure_ascii=False),
            window_start=self.window_start,
            window_end=self.window_end,
        )
        db.session.add(log)
        self._finalised = True
        self._record = log
        return log

    def _add_entry(self, level: str, message: str) -> None:
        text = message.strip()
        if not text:
            return
        self.entries.append({"level": level, "message": text})
        logger = getattr(current_app, "logger", None)
        if logger is not None:
            log_level = self.LEVELS.get(level, logging.INFO)
            logger.log(log_level, "[%s] %s", self.course.name, text)


def daterange(start: date, end: date) -> Iterable[date]:
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    return max(a_start, b_start) < min(a_end, b_end)


def fits_in_windows(start: time, end: time) -> bool:
    for window_start, window_end in WORKING_WINDOWS:
        if window_start <= start and end <= window_end:
            return True
    return False


def find_available_room(
    course: Course,
    start: datetime,
    end: datetime,
    *,
    required_capacity: int | None = None,
) -> Optional[Room]:
    rooms = Room.query.order_by(Room.capacity.asc()).all()
    required_students = required_capacity or 1
    required_equipment_ids = {equipment.id for equipment in course.equipments}
    required_software_ids = {software.id for software in course.softwares}

    best_room: Room | None = None
    best_missing_softwares: int | None = None

    for room in rooms:
        if room.capacity < required_students:
            continue
        if course.requires_computers and room.computers <= 0:
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


def find_available_teacher(
    course: Course,
    start: datetime,
    end: datetime,
    *,
    link: CourseClassLink | None = None,
    subgroup_label: str | None = None,
    segments: Optional[list[tuple[datetime, datetime]]] = None,
) -> Optional[Teacher]:
    preferred: list[Teacher] = []
    if link is not None:
        for assigned in link.preferred_teachers(subgroup_label):
            if assigned is not None and assigned not in preferred:
                preferred.append(assigned)

    if course.teachers:
        fallback_pool = list(course.teachers)
    else:
        fallback_pool = Teacher.query.all()

    candidates = preferred + [teacher for teacher in fallback_pool if teacher not in preferred]
    for teacher in sorted(candidates, key=lambda t: t.name.lower()):
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


def _class_hours_needed(
    course: Course, class_group: ClassGroup, subgroup_label: str | None = None
) -> int:
    target_label = _normalise_label(subgroup_label)
    existing = sum(
        session.duration_hours
        for session in course.sessions
        if session.class_group_id == class_group.id
        and _normalise_label(session.subgroup_label) == target_label
    )
    required_total = course.sessions_required * course.session_length_hours
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


def _collect_contiguous_slots(start_index: int, length: int) -> list[tuple[time, time]] | None:
    slots: list[tuple[time, time]] = []
    previous_end: time | None = None
    for offset in range(length):
        index = start_index + offset
        if index >= len(SCHEDULE_SLOTS):
            return None
        slot_start, slot_end = SCHEDULE_SLOTS[index]
        if previous_end:
            gap = datetime.combine(date.min, slot_start) - datetime.combine(
                date.min, previous_end
            )
            if gap < timedelta(0):
                return None
            if gap > MAX_SLOT_GAP and (previous_end, slot_start) not in EXTENDED_BREAKS:
                return None
        slots.append((slot_start, slot_end))
        previous_end = slot_end
    return slots


def _schedule_block_for_day(
    *,
    course: Course,
    class_group: ClassGroup,
    link: CourseClassLink,
    subgroup_label: str | None,
    day: date,
    desired_hours: int,
    base_offset: int,
) -> list[Session] | None:
    placement = _try_full_block(
        course=course,
        class_group=class_group,
        link=link,
        subgroup_label=subgroup_label,
        day=day,
        desired_hours=desired_hours,
        base_offset=base_offset,
    )
    if placement:
        return placement
    if desired_hours <= 1:
        return None
    return _try_split_block(
        course=course,
        class_group=class_group,
        link=link,
        subgroup_label=subgroup_label,
        day=day,
        desired_hours=desired_hours,
        base_offset=base_offset,
    )


def _try_full_block(
    *,
    course: Course,
    class_group: ClassGroup,
    link: CourseClassLink,
    subgroup_label: str | None,
    day: date,
    desired_hours: int,
    base_offset: int,
) -> list[Session] | None:
    required_capacity = course.capacity_needed_for(class_group)
    for offset in range(len(START_TIMES)):
        slot_index = (base_offset + offset) % len(START_TIMES)
        slot_start_time = START_TIMES[slot_index]
        start_dt = datetime.combine(day, slot_start_time)
        end_dt = start_dt + timedelta(hours=desired_hours)
        if not fits_in_windows(start_dt.time(), end_dt.time()):
            continue
        if not class_group.is_available_during(start_dt, end_dt):
            continue
        teacher = find_available_teacher(
            course,
            start_dt,
            end_dt,
            link=link,
            subgroup_label=subgroup_label,
        )
        if not teacher:
            continue
        room = find_available_room(
            course,
            start_dt,
            end_dt,
            required_capacity=required_capacity,
        )
        if not room:
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
) -> list[Session] | None:
    segment_count = desired_hours
    required_capacity = course.capacity_needed_for(class_group)
    slot_count = len(SCHEDULE_SLOTS)
    for offset in range(slot_count):
        start_index = (base_offset + offset) % slot_count
        contiguous = _collect_contiguous_slots(start_index, segment_count)
        if not contiguous:
            continue
        if not all(fits_in_windows(start, end) for start, end in contiguous):
            continue
        segment_datetimes = [
            (datetime.combine(day, slot_start), datetime.combine(day, slot_end))
            for slot_start, slot_end in contiguous
        ]
        start_dt = segment_datetimes[0][0]
        end_dt = segment_datetimes[-1][1]
        if not all(
            class_group.is_available_during(segment_start, segment_end)
            for segment_start, segment_end in segment_datetimes
        ):
            continue
        teacher = find_available_teacher(
            course,
            start_dt,
            end_dt,
            link=link,
            subgroup_label=subgroup_label,
            segments=segment_datetimes,
        )
        if not teacher:
            continue
        rooms: list[Room] = []
        valid = True
        for seg_start, seg_end in segment_datetimes:
            if any(
                overlaps(existing.start_time, existing.end_time, seg_start, seg_end)
                for existing in teacher.sessions
            ):
                valid = False
                break
            room = find_available_room(
                course,
                seg_start,
                seg_end,
                required_capacity=required_capacity,
            )
            if not room:
                valid = False
                break
            rooms.append(room)
        if not valid:
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
) -> list[Session] | None:
    placement = _cm_try_full_block(
        course=course,
        class_groups=class_groups,
        primary_link=primary_link,
        day=day,
        desired_hours=desired_hours,
        base_offset=base_offset,
    )
    if placement:
        return placement
    if desired_hours <= 1:
        return None
    return _cm_try_split_block(
        course=course,
        class_groups=class_groups,
        primary_link=primary_link,
        day=day,
        desired_hours=desired_hours,
        base_offset=base_offset,
    )


def _cm_try_full_block(
    *,
    course: Course,
    class_groups: list[ClassGroup],
    primary_link: CourseClassLink | None,
    day: date,
    desired_hours: int,
    base_offset: int,
) -> list[Session] | None:
    if not class_groups:
        return None
    required_capacity = sum(course.capacity_needed_for(group) for group in class_groups)
    primary_class = class_groups[0]
    for offset in range(len(START_TIMES)):
        slot_index = (base_offset + offset) % len(START_TIMES)
        slot_start_time = START_TIMES[slot_index]
        start_dt = datetime.combine(day, slot_start_time)
        end_dt = start_dt + timedelta(hours=desired_hours)
        if not fits_in_windows(start_dt.time(), end_dt.time()):
            continue
        if not all(
            class_group.is_available_during(start_dt, end_dt)
            for class_group in class_groups
        ):
            continue
        teacher = find_available_teacher(
            course,
            start_dt,
            end_dt,
            link=primary_link,
            subgroup_label=None,
        )
        if not teacher:
            continue
        room = find_available_room(
            course,
            start_dt,
            end_dt,
            required_capacity=required_capacity,
        )
        if not room:
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
) -> list[Session] | None:
    if not class_groups:
        return None
    segment_count = desired_hours
    required_capacity = sum(course.capacity_needed_for(group) for group in class_groups)
    slot_count = len(SCHEDULE_SLOTS)
    primary_class = class_groups[0]
    for offset in range(slot_count):
        start_index = (base_offset + offset) % slot_count
        contiguous = _collect_contiguous_slots(start_index, segment_count)
        if not contiguous:
            continue
        if not all(fits_in_windows(start, end) for start, end in contiguous):
            continue
        segment_datetimes = [
            (datetime.combine(day, slot_start), datetime.combine(day, slot_end))
            for slot_start, slot_end in contiguous
        ]
        if not all(
            class_group.is_available_during(segment_start, segment_end)
            for class_group in class_groups
            for segment_start, segment_end in segment_datetimes
        ):
            continue
        teacher = find_available_teacher(
            course,
            segment_datetimes[0][0],
            segment_datetimes[-1][1],
            link=primary_link,
            subgroup_label=None,
            segments=segment_datetimes,
        )
        if not teacher:
            continue
        rooms: list[Room] = []
        valid = True
        for seg_start, seg_end in segment_datetimes:
            if any(
                overlaps(existing.start_time, existing.end_time, seg_start, seg_end)
                for existing in teacher.sessions
            ):
                valid = False
                break
            room = find_available_room(
                course,
                seg_start,
                seg_end,
                required_capacity=required_capacity,
            )
            if not room:
                valid = False
                break
            rooms.append(room)
        if not valid:
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
    start_candidates = [value for value in (course.start_date, window_start) if value]
    end_candidates = [value for value in (course.end_date, window_end) if value]
    if not start_candidates or not end_candidates:
        raise ValueError(
            "Définissez des dates de début et de fin pour le cours ou indiquez une période de planification."
        )
    start = max(start_candidates)
    end = min(end_candidates)
    if start > end:
        raise ValueError(
            "La période choisie n'intersecte pas la fenêtre du cours."
        )
    return start, end


def generate_schedule(
    course: Course,
    *,
    window_start: date | None = None,
    window_end: date | None = None,
) -> list[Session]:
    reporter = ScheduleReporter(course)
    created_sessions: list[Session] = []

    try:
        schedule_start, schedule_end = _resolve_schedule_window(
            course, window_start, window_end
        )
        reporter.set_window(schedule_start, schedule_end)
    except ValueError as exc:
        reporter.error(str(exc))
        reporter.summary = str(exc)
        reporter.finalise(len(created_sessions))
        raise

    if not course.classes:
        message = "Associez au moins une classe au cours avant de planifier."
        reporter.error(message)
        reporter.summary = message
        reporter.finalise(0)
        raise ValueError(message)

    reporter.info(
        f"Durée cible des séances : {course.session_length_hours} h — "
        f"{course.sessions_required} occurrence(s) par groupe"
    )

    created_sessions = []
    slot_length_hours = max(int(course.session_length_hours), 1)

    links = sorted(course.class_links, key=lambda link: link.class_group.name.lower())
    if links:
        reporter.info(
            "Classes associées : "
            + ", ".join(link.class_group.name for link in links)
        )
    else:
        reporter.warning("Aucune classe n'est associée au cours.")
    if course.is_cm:
        class_groups = [link.class_group for link in links]
        if not class_groups:
            message = "Associez au moins une classe au cours avant de planifier."
            reporter.error(message)
            reporter.summary = message
            reporter.finalise(0)
            raise ValueError(message)
        target_ids = {group.id for group in class_groups}
        existing_day_hours = _cm_existing_hours_by_day(course, target_ids)
        total_required = course.sessions_required * course.session_length_hours
        already_scheduled = sum(existing_day_hours.values())
        hours_remaining = max(total_required - already_scheduled, 0)
        reporter.info(
            f"Heures requises : {total_required} h — déjà planifiées : {already_scheduled} h"
        )
        if hours_remaining == 0:
            reporter.info("Toutes les heures requises sont déjà planifiées.")
            reporter.finalise(len(created_sessions))
            return created_sessions
        available_days = [
            day
            for day in sorted(daterange(schedule_start, schedule_end))
            if day.weekday() < 5 and all(group.is_available_on(day) for group in class_groups)
        ]
        if not available_days:
            reporter.warning(
                "Aucune journée commune disponible pour les classes sélectionnées"
            )
            reporter.finalise(len(created_sessions))
            return created_sessions
        per_day_hours = {day: existing_day_hours.get(day, 0) for day in available_days}
        day_indices = {day: index for index, day in enumerate(available_days)}
        slot_length_hours = max(int(course.session_length_hours), 1)
        blocks_total = max((hours_remaining + slot_length_hours - 1) // slot_length_hours, 1)
        block_index = 0
        primary_link = links[0] if links else None
        while hours_remaining > 0:
            desired_hours = min(slot_length_hours, hours_remaining)
            if len(available_days) == 1:
                anchor_index = 0
            elif blocks_total == 1:
                anchor_index = len(available_days) // 2
            else:
                anchor_position = (
                    block_index / (blocks_total - 1)
                ) * (len(available_days) - 1)
                anchor_index = round(anchor_position)
            anchor_index = max(0, min(anchor_index, len(available_days) - 1))

            ordered_days = sorted(
                available_days,
                key=lambda d: (
                    per_day_hours[d],
                    abs(day_indices[d] - anchor_index),
                    day_indices[d],
                ),
            )

            placed = False
            for day in ordered_days:
                base_offset = int(per_day_hours[day])
                block_sessions = _cm_schedule_block_for_day(
                    course=course,
                    class_groups=class_groups,
                    primary_link=primary_link,
                    day=day,
                    desired_hours=desired_hours,
                    base_offset=base_offset,
                )
                if not block_sessions:
                    continue
                created_sessions.extend(block_sessions)
                for session in block_sessions:
                    reporter.session_created(session)
                block_hours = sum(session.duration_hours for session in block_sessions)
                per_day_hours[day] += block_hours
                hours_remaining = max(hours_remaining - block_hours, 0)
                block_index += 1
                placed = True
                break

            if not placed:
                break

        if hours_remaining > 0:
            reporter.warning(
                f"Impossible de planifier {hours_remaining} heure(s) supplémentaire(s) (cours magistral)"
            )
        reporter.info(f"Total de séances générées : {len(created_sessions)}")
        reporter.finalise(len(created_sessions))
        return created_sessions
    for link in links:
        class_group = link.class_group
        for subgroup_label in link.group_labels():
            hours_needed = _class_hours_needed(course, class_group, subgroup_label)
            if hours_needed == 0:
                continue
            available_days = [
                day
                for day in sorted(daterange(schedule_start, schedule_end))
                if day.weekday() < 5 and class_group.is_available_on(day)
            ]
            if not available_days:
                reporter.warning(
                    f"Aucune journée disponible pour {class_group.name} sur la période"
                )
                continue

            existing_day_hours = _existing_hours_by_day(course, class_group, subgroup_label)
            day_indices = {day: index for index, day in enumerate(available_days)}
            per_day_hours = {
                day: existing_day_hours.get(day, 0) for day in available_days
            }
            blocks_total = max(
                (hours_needed + slot_length_hours - 1) // slot_length_hours,
                1,
            )
            block_index = 0
            hours_remaining = hours_needed

            while hours_remaining > 0:
                desired_hours = min(slot_length_hours, hours_remaining)
                if len(available_days) == 1:
                    anchor_index = 0
                elif blocks_total == 1:
                    anchor_index = len(available_days) // 2
                else:
                    anchor_position = (
                        block_index / (blocks_total - 1)
                    ) * (len(available_days) - 1)
                    anchor_index = round(anchor_position)
                anchor_index = max(0, min(anchor_index, len(available_days) - 1))

                ordered_days = sorted(
                    available_days,
                    key=lambda d: (
                        per_day_hours[d],
                        abs(day_indices[d] - anchor_index),
                        day_indices[d],
                    ),
                )

                placed = False
                for day in ordered_days:
                    base_offset = int(per_day_hours[day])
                    block_sessions = _schedule_block_for_day(
                        course=course,
                        class_group=class_group,
                        link=link,
                        subgroup_label=subgroup_label,
                        day=day,
                        desired_hours=desired_hours,
                        base_offset=base_offset,
                    )
                    if not block_sessions:
                        continue
                    created_sessions.extend(block_sessions)
                    for session in block_sessions:
                        reporter.session_created(session)
                    block_hours = sum(
                        session.duration_hours for session in block_sessions
                    )
                    per_day_hours[day] += block_hours
                    hours_remaining = max(hours_remaining - block_hours, 0)
                    block_index += 1
                    placed = True
                    break

                if not placed:
                    break

            if hours_remaining > 0:
                reporter.warning(
                    f"Impossible de planifier {hours_remaining} heure(s) pour {class_group.name}"
                )
    reporter.info(f"Total de séances générées : {len(created_sessions)}")
    reporter.finalise(len(created_sessions))
    return created_sessions
