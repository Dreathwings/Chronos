from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from dataclasses import dataclass
from functools import lru_cache, partial
from datetime import date, datetime, time, timedelta
from typing import Callable, Iterable, List, Optional, Set

from flask import current_app

from . import db
from .models import (
    ClassGroup,
    Course,
    CourseClassLink,
    CourseScheduleLog,
    ClosingPeriod,
    Equipment,
    Room,
    Session,
    Teacher,
)
from .progress import NullScheduleProgress, ScheduleProgress
from sqlalchemy.orm import selectinload

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

COURSE_TYPE_CHRONOLOGY: dict[str, int] = {
    "CM": 0,
    "TD": 1,
    "TP": 2,
    "TEST": 3,
    "EVAL": 3,
    "Eval": 3,
}


@dataclass(frozen=True)
class PlacementDecision:
    day: date
    base_offset: int
    desired_hours: int


@dataclass
class SearchState:
    plan: list[PlacementDecision]
    created_sessions: list["Session"]
    per_day_hours: dict[date, int]
    weekday_frequencies: Counter[int]
    hours_remaining: float
    block_index: int
    score: tuple[float, float, float, float]


@dataclass
class GlobalSearchContext:
    course: Course
    groups: list[ClassGroup]
    available_days: list[date]
    day_indices: dict[date, int]
    slot_length_hours: int
    subgroup_label: str | None
    schedule_callable: Callable[..., list["Session"] | None]
    require_exact_attendees: bool = False
    day_branch_limit: int = 5
    offset_branch_limit: int = 3
    beam_width: int = 5

    def clone_state(
        self,
        state: SearchState,
    ) -> SearchState:
        return SearchState(
            plan=list(state.plan),
            created_sessions=list(state.created_sessions),
            per_day_hours=dict(state.per_day_hours),
            weekday_frequencies=Counter(state.weekday_frequencies),
            hours_remaining=state.hours_remaining,
            block_index=state.block_index,
            score=state.score,
        )

    def score_state(self, state: SearchState) -> tuple[float, float, float, float]:
        imbalance = 0.0
        if state.per_day_hours:
            values = list(state.per_day_hours.values())
            average = sum(values) / len(values)
            imbalance = sum((value - average) ** 2 for value in values)
        weekday_peak = (
            max(state.weekday_frequencies.values())
            if state.weekday_frequencies
            else 0.0
        )
        return (
            state.hours_remaining,
            imbalance,
            weekday_peak,
            -float(state.block_index),
        )

    def initial_state(
        self,
        *,
        created_sessions: list["Session"],
        per_day_hours: dict[date, int],
        weekday_frequencies: Counter[int],
        hours_remaining: float,
        block_index: int,
    ) -> SearchState:
        state = SearchState(
            plan=[],
            created_sessions=list(created_sessions),
            per_day_hours=dict(per_day_hours),
            weekday_frequencies=Counter(weekday_frequencies),
            hours_remaining=hours_remaining,
            block_index=block_index,
            score=(0.0, 0.0, 0.0, 0.0),
        )
        state.score = self.score_state(state)
        return state

    def matching_sessions(self, pending_sessions: Iterable["Session"]) -> list["Session"]:
        return _matching_sessions_for_groups(
            self.course,
            self.groups,
            pending_sessions=pending_sessions,
            subgroup_label=self.subgroup_label,
            require_exact_attendees=self.require_exact_attendees,
        )

    def continuity_info(
        self,
        pending_sessions: Iterable["Session"],
    ) -> tuple[int | None, int | None, date | None]:
        matching_sessions = self.matching_sessions(pending_sessions)
        base_session = matching_sessions[0] if matching_sessions else None
        continuity_weekday = (
            base_session.start_time.weekday() if base_session is not None else None
        )
        continuity_slot_index: int | None = None
        if base_session is not None:
            try:
                continuity_slot_index = START_TIMES.index(base_session.start_time.time())
            except ValueError:
                continuity_slot_index = None
        continuity_target_date: date | None = None
        if base_session is not None:
            base_date = base_session.start_time.date()
            week_offsets = [
                max(0, (session.start_time.date() - base_date).days // 7)
                for session in matching_sessions
                if session.start_time.date() >= base_date
            ]
            next_offset = max(week_offsets, default=0) + 1
            continuity_target_date = base_date + timedelta(days=7 * next_offset)
        return continuity_weekday, continuity_slot_index, continuity_target_date

    def ordered_days(
        self,
        state: SearchState,
        *,
        blocks_total: int,
        continuity_weekday: int | None,
        continuity_target_date: date | None,
    ) -> list[date]:
        if not self.available_days:
            return []
        if len(self.available_days) == 1:
            anchor_index = 0
        elif blocks_total == 1:
            anchor_index = len(self.available_days) // 2
        else:
            anchor_position = (
                (state.block_index) / (max(blocks_total - 1, 1))
            ) * (len(self.available_days) - 1)
            anchor_index = round(anchor_position)
        anchor_index = max(0, min(anchor_index, len(self.available_days) - 1))

        def _sort_key(day: date) -> tuple[int, int, int, int, int, int, int]:
            anchor_distance = abs(self.day_indices.get(day, 0) - anchor_index)
            continuity_flag = 1
            future_bias = 0
            continuity_distance = anchor_distance
            if continuity_weekday is not None and day.weekday() == continuity_weekday:
                continuity_flag = 0
                if continuity_target_date is not None:
                    future_bias = 0 if day >= continuity_target_date else 1
                    continuity_distance = abs((day - continuity_target_date).days)
                else:
                    continuity_distance = 0
            frequency_penalty = -state.weekday_frequencies.get(day.weekday(), 0)
            per_day_penalty = state.per_day_hours.get(day, 0)
            return (
                continuity_flag,
                future_bias,
                continuity_distance,
                frequency_penalty,
                per_day_penalty,
                anchor_distance,
                self.day_indices.get(day, 0),
            )

        ordered = sorted(self.available_days, key=_sort_key)
        return ordered

    def _candidate_offsets(
        self,
        *,
        day: date,
        desired_hours: int,
        state: SearchState,
        continuity_weekday: int | None,
        continuity_slot_index: int | None,
    ) -> list[int]:
        offsets: list[int] = []
        if (
            continuity_slot_index is not None
            and continuity_weekday is not None
            and day.weekday() == continuity_weekday
        ):
            offsets.append(continuity_slot_index)
        if desired_hours == 1:
            adjacency_offsets = _one_hour_adjacency_offsets(
                self.groups,
                day,
                pending_sessions=state.created_sessions,
                subgroup_label=self.subgroup_label,
            )
            for offset in adjacency_offsets:
                if offset not in offsets:
                    offsets.append(offset)
        preferred_slot = _preferred_slot_index_for_groups(
            self.course,
            self.groups,
            day,
            pending_sessions=state.created_sessions,
            subgroup_label=self.subgroup_label,
        )
        if preferred_slot is not None and preferred_slot not in offsets:
            offsets.append(preferred_slot)
        fallback_offset = int(state.per_day_hours.get(day, 0))
        if fallback_offset not in offsets:
            offsets.append(fallback_offset)
        return offsets

    def day_is_valid(
        self,
        *,
        day: date,
        desired_hours: int,
        pending_sessions: list["Session"],
    ) -> bool:
        for group in self.groups:
            if group is None:
                continue
            if has_weekly_course_conflict(
                self.course,
                group,
                day,
                pending_sessions=pending_sessions,
                subgroup_label=self.subgroup_label,
                additional_hours=desired_hours,
            ):
                return False
            if not _day_respects_chronology(
                self.course,
                group,
                day,
                pending_sessions,
                subgroup_label=self.subgroup_label,
            ):
                return False
        return True

    def simulate_placement(
        self,
        state: SearchState,
        *,
        day: date,
        base_offset: int,
        desired_hours: int,
    ) -> SearchState | None:
        if not self.day_is_valid(
            day=day,
            desired_hours=desired_hours,
            pending_sessions=state.created_sessions,
        ):
            return None
        nested = db.session.begin_nested()
        try:
            placement = self.schedule_callable(
                day=day,
                desired_hours=desired_hours,
                base_offset=base_offset,
                pending_sessions=state.created_sessions,
                reporter=None,
            )
            if not placement:
                return None
            new_state = self.clone_state(state)
            decision = PlacementDecision(
                day=day,
                base_offset=base_offset,
                desired_hours=desired_hours,
            )
            new_state.plan.append(decision)
            new_state.created_sessions.extend(placement)
            block_hours = sum(session.duration_hours for session in placement)
            new_state.per_day_hours[day] = new_state.per_day_hours.get(day, 0) + block_hours
            for session in placement:
                new_state.weekday_frequencies[session.start_time.weekday()] += 1
            new_state.hours_remaining = max(new_state.hours_remaining - block_hours, 0)
            new_state.block_index += 1
            new_state.score = self.score_state(new_state)
            return new_state
        finally:
            nested.rollback()


def _beam_search_plan(
    *,
    context: GlobalSearchContext,
    created_sessions: list["Session"],
    per_day_hours: dict[date, int],
    weekday_frequencies: Counter[int],
    hours_remaining: float,
    block_index: int,
    lookahead: int = 3,
) -> list[PlacementDecision] | None:
    if hours_remaining <= 0:
        return None
    state = context.initial_state(
        created_sessions=created_sessions,
        per_day_hours=per_day_hours,
        weekday_frequencies=weekday_frequencies,
        hours_remaining=hours_remaining,
        block_index=block_index,
    )
    best_state: SearchState | None = None
    frontier: list[SearchState] = [state]
    for _ in range(max(lookahead, 1)):
        next_frontier: list[SearchState] = []
        for current in frontier:
            if current.hours_remaining <= 0:
                if best_state is None or current.score < best_state.score:
                    best_state = current
                next_frontier.append(current)
                continue
            desired_hours = min(context.slot_length_hours, int(current.hours_remaining))
            if desired_hours <= 0:
                desired_hours = 1
            blocks_total = max(
                (int(current.hours_remaining) + context.slot_length_hours - 1)
                // context.slot_length_hours,
                1,
            )
            (
                continuity_weekday,
                continuity_slot_index,
                continuity_target,
            ) = context.continuity_info(current.created_sessions)
            ordered_days = context.ordered_days(
                current,
                blocks_total=blocks_total,
                continuity_weekday=continuity_weekday,
                continuity_target_date=continuity_target,
            )
            day_count = 0
            for day in ordered_days:
                if not context.day_is_valid(
                    day=day,
                    desired_hours=desired_hours,
                    pending_sessions=current.created_sessions,
                ):
                    continue
                offsets = context._candidate_offsets(
                    day=day,
                    desired_hours=desired_hours,
                    state=current,
                    continuity_weekday=continuity_weekday,
                    continuity_slot_index=continuity_slot_index,
                )
                if not offsets:
                    continue
                day_count += 1
                for base_offset in offsets[: context.offset_branch_limit]:
                    new_state = context.simulate_placement(
                        current,
                        day=day,
                        base_offset=base_offset,
                        desired_hours=desired_hours,
                    )
                    if new_state is None:
                        continue
                    next_frontier.append(new_state)
                if day_count >= context.day_branch_limit:
                    break
        if not next_frontier:
            break
        next_frontier.sort(key=lambda item: item.score)
        frontier = next_frontier[: context.beam_width]
        for candidate in frontier:
            if best_state is None or candidate.score < best_state.score:
                best_state = candidate
    if best_state is None or not best_state.plan:
        return None
    if best_state.hours_remaining >= state.hours_remaining:
        return None
    return best_state.plan[len(state.plan) :]


def _segment_duration_hours(start: datetime, end: datetime) -> float:
    delta = end - start
    return max(delta.total_seconds() / 3600.0, 0.0)


@lru_cache(maxsize=256)
def _room_candidate_ids(
    required_students: int,
    required_posts: int,
    equipment_ids: tuple[int, ...],
) -> tuple[int, ...]:
    query = Room.query
    if required_students:
        query = query.filter(Room.capacity >= required_students)
    if required_posts:
        query = query.filter(Room.computers >= required_posts)
    for equipment_id in equipment_ids:
        query = query.filter(Room.equipments.any(Equipment.id == equipment_id))
    ids = [
        room_id
        for (room_id,) in query.with_entities(Room.id)
        .order_by(Room.capacity.asc(), Room.name.asc())
        .all()
        if room_id is not None
    ]
    return tuple(ids)


def _ordered_candidate_rooms(candidate_ids: tuple[int, ...]) -> list[Room]:
    if not candidate_ids:
        return []
    rooms = (
        Room.query.filter(Room.id.in_(candidate_ids))
        .options(
            selectinload(Room.softwares),
            selectinload(Room.equipments),
            selectinload(Room.sessions),
        )
        .all()
    )
    by_id = {room.id: room for room in rooms if room.id is not None}
    return [by_id[room_id] for room_id in candidate_ids if room_id in by_id]


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


class ScheduleReporter:
    MAX_DETAILED_ENTRIES = 50
    MAX_TOTAL_ENTRIES = 120
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
            messages=json.dumps(self._serialise_entries(), ensure_ascii=False),
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
        if level != "info":
            self.entries.append({"level": level, "message": text})
        logger = getattr(current_app, "logger", None)
        if logger is not None:
            log_level = self.LEVELS.get(level, logging.INFO)
            logger.log(log_level, "[%s] %s", self.course.name, text)

    def _serialise_entries(self) -> list[dict[str, str]]:
        if not self.entries:
            return []
        if len(self.entries) <= self.MAX_DETAILED_ENTRIES:
            return list(self.entries)

        detailed = list(self.entries[: self.MAX_DETAILED_ENTRIES])
        summary_counts: dict[tuple[str, str], int] = {}
        summary_order: list[tuple[str, str]] = []
        for entry in self.entries[self.MAX_DETAILED_ENTRIES :]:
            key = (entry["level"], entry["message"])
            if key not in summary_counts:
                summary_counts[key] = 0
                summary_order.append(key)
            summary_counts[key] += 1

        for level, message in summary_order:
            count = summary_counts[(level, message)]
            if count > 1:
                label = f"{message} (résumé {count}×)"
            else:
                label = f"{message} (résumé)"
            detailed.append({"level": level, "message": label})
            if len(detailed) >= self.MAX_TOTAL_ENTRIES:
                break
        return detailed[: self.MAX_TOTAL_ENTRIES]


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
    required_students = max(required_capacity or 1, 1)
    required_posts = course.required_computer_posts()
    equipment_ids = tuple(
        sorted(equipment.id for equipment in course.equipments if equipment.id)
    )
    candidate_ids = _room_candidate_ids(required_students, required_posts, equipment_ids)
    candidates = _ordered_candidate_rooms(candidate_ids)
    candidate_id_set = {room.id for room in candidates if room.id is not None}

    preferred_rooms: list[Room] = []
    preferred_room_ids: set[int] = set()
    if course.preferred_rooms:
        preferred_rooms = sorted(
            [
                room
                for room in course.preferred_rooms
                if room is not None and room.id in candidate_id_set
            ],
            key=lambda room: (room.capacity or 0, (room.name or "").lower()),
        )

    ordered_rooms: list[Room] = []
    seen: set[int] = set()
    for room in preferred_rooms + candidates:
        room_id = room.id
        if room_id is None:
            continue
        if room_id in seen:
            continue
        ordered_rooms.append(room)
        seen.add(room_id)

    required_software_ids = {software.id for software in course.softwares}

    best_room: Room | None = None
    best_missing_softwares: int | None = None

    for room in ordered_rooms:
        if room.capacity < required_students:
            continue
        if required_posts and (room.computers or 0) < required_posts:
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
        if (
            best_room is None
            or best_missing_softwares is None
            or missing_count < best_missing_softwares
        ):
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
    preferred: list[Teacher] = []
    if link is not None:
        for assigned in link.preferred_teachers(subgroup_label):
            if assigned is not None and assigned not in preferred:
                preferred.append(assigned)
        fallback_pool = link.assigned_teachers()
    elif course.teachers:
        fallback_pool = list(course.teachers)
    else:
        fallback_pool = Teacher.query.all()

    candidates = preferred + [teacher for teacher in fallback_pool if teacher not in preferred]
    if not candidates:
        if link is not None:
            return "Aucun enseignant n'est associé à cette classe dans la section « Link teacher »."
        return "Aucun enseignant n'est associé au cours."

    segments_to_check = segments or [(start, end)]
    reasons: list[str] = []
    for teacher in sorted(candidates, key=lambda t: t.name.lower()):
        if not all(
            teacher.is_available_during(segment_start, segment_end)
            for segment_start, segment_end in segments_to_check
        ):
            reasons.append(f"{teacher.name} est déclaré indisponible sur ce créneau.")
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
    start = day - timedelta(days=day.weekday())
    end = start + timedelta(days=6)
    return start, end


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
    target_day = start.date() if isinstance(start, datetime) else start
    week_start, week_end = _week_bounds(target_day)
    weekly_limit = max(int(course.session_length_hours), 0)
    if weekly_limit == 0:
        return False
    scheduled_hours = _course_class_hours_in_week(
        course,
        class_group,
        week_start,
        week_end,
        pending_sessions,
        subgroup_label=subgroup_label,
        ignore_session_id=ignore_session_id,
    )
    extra_hours = (
        weekly_limit if additional_hours is None else max(int(additional_hours), 0)
    )
    return scheduled_hours + extra_hours > weekly_limit


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
    preferred: list[Teacher] = []
    allowed_ids: set[int] | None = None
    if link is not None:
        for assigned in link.preferred_teachers(subgroup_label):
            if assigned is not None and assigned not in preferred:
                preferred.append(assigned)

    if link is not None:
        fallback_pool = link.assigned_teachers()
        allowed_ids = {teacher.id for teacher in fallback_pool if teacher.id is not None}
    elif course.teachers:
        fallback_pool = list(course.teachers)
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

    segments_to_check = segments or [(start, end)]
    segment_days = {segment_start.date() for segment_start, _ in segments_to_check}
    segment_hours_by_day: dict[date, float] = defaultdict(float)
    for segment_start, segment_end in segments_to_check:
        segment_hours_by_day[segment_start.date()] += _segment_duration_hours(
            segment_start, segment_end
        )

    preferred_ids = {teacher.id for teacher in preferred if teacher and teacher.id}

    viable: list[tuple[tuple[int | float, ...], Teacher]] = []
    for teacher in candidates:
        availability_cache = teacher.__dict__.setdefault("_availability_cache", {})
        available = True
        for segment_start, segment_end in segments_to_check:
            cache_key = (segment_start, segment_end)
            if cache_key not in availability_cache:
                availability_cache[cache_key] = teacher.is_available_during(
                    segment_start, segment_end
                )
            if not availability_cache[cache_key]:
                available = False
                break
        if not available:
            continue

        relevant_sessions = [
            session
            for session in teacher.sessions
            if session.start_time.date() in segment_days
        ]
        conflict = False
        for session in relevant_sessions:
            for segment_start, segment_end in segments_to_check:
                if overlaps(session.start_time, session.end_time, segment_start, segment_end):
                    conflict = True
                    break
            if conflict:
                break
        if conflict:
            continue

        affinity = 3
        teacher_id = teacher.id
        if teacher_id is not None and teacher_id in preferred_ids:
            affinity = 0
        elif target_class_ids and any(
            _session_attendee_ids(session) == target_class_ids
            for session in teacher.sessions
        ):
            affinity = min(affinity, 1)
        elif any(session.course_id == course.id for session in teacher.sessions):
            affinity = min(affinity, 2)

        day_penalty = 0.0
        for day, added_hours in segment_hours_by_day.items():
            existing = sum(
                session.duration_hours
                for session in teacher.sessions
                if session.start_time.date() == day
            )
            day_penalty = max(day_penalty, existing + added_hours)

        total_assignments = len(teacher.sessions)
        score = (affinity, day_penalty, total_assignments, (teacher.name or "").lower())
        viable.append((score, teacher))

    if not viable:
        return None

    viable.sort(key=lambda item: item[0])
    return viable[0][1]


def _persist_sessions(sessions: Iterable[Session]) -> None:
    to_persist = [session for session in sessions if session is not None]
    if not to_persist:
        return
    # Un flush unique conserve la parade au bug MariaDB mentionné dans les
    # commentaires historiques tout en évitant des allers-retours répétés avec
    # la base de données pour chaque séance.
    db.session.add_all(to_persist)
    db.session.flush()


def _normalise_label(label: str | None) -> str:
    return (label or "").upper()


def _week_start_for(day: date) -> date:
    return day - timedelta(days=day.weekday())


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
        _persist_sessions([session])
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
            sessions.append(session)
        _persist_sessions(sessions)
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
        _persist_sessions([session])
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
            sessions.append(session)
        _persist_sessions(sessions)
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
    progress = progress or NullScheduleProgress()
    reporter = ScheduleReporter(course)
    created_sessions: list[Session] = []
    placement_failures: list[str] = []

    try:
        schedule_start, schedule_end = _resolve_schedule_window(
            course, window_start, window_end
        )
    except ValueError as exc:
        reporter.error(str(exc))
        reporter.summary = str(exc)
        reporter.finalise(len(created_sessions))
        raise

    normalised_weeks: list[tuple[date, date]] = []
    if allowed_weeks:
        for week_start, week_end in allowed_weeks:
            if week_start is None or week_end is None:
                continue
            if week_end < week_start:
                week_start, week_end = week_end, week_start
            normalised_weeks.append((week_start, week_end))
        normalised_weeks.sort(key=lambda span: span[0])
        truncated_weeks: list[tuple[date, date]] = []
        for week_start, week_end in normalised_weeks:
            if week_end < schedule_start or week_start > schedule_end:
                continue
            span_start = max(week_start, schedule_start)
            span_end = min(week_end, schedule_end)
            if span_start > span_end:
                continue
            truncated_weeks.append((span_start, span_end))
        normalised_weeks = truncated_weeks
        if not normalised_weeks:
            message = (
                "Les semaines sélectionnées ne recoupent pas la fenêtre du cours."
            )
            reporter.error(message)
            reporter.summary = message
            reporter.finalise(0)
            raise ValueError(message)
        schedule_start = normalised_weeks[0][0]
        schedule_end = normalised_weeks[-1][1]
        reporter.set_window(schedule_start, schedule_end)
    else:
        reporter.set_window(schedule_start, schedule_end)

    closed_days = _closed_days_between(schedule_start, schedule_end)
    if closed_days:
        reporter.info(
            f"{len(closed_days)} jour(s) exclus pour fermeture (vacances)"
        )

    allowed_days: set[date] | None = None
    if normalised_weeks:
        allowed_days = set()
        removed_weeks: list[date] = []
        for span_start, span_end in normalised_weeks:
            span_days = [
                day
                for day in daterange(span_start, span_end)
                if day not in closed_days
            ]
            if not span_days:
                removed_weeks.append(span_start)
                continue
            allowed_days.update(span_days)
        if removed_weeks:
            removed_labels = ", ".join(
                week_start.strftime("%d/%m/%Y") for week_start in removed_weeks
            )
            reporter.info(
                "Semaines exclues pour congés : " + removed_labels
            )
        if not allowed_days:
            message = (
                "Les semaines sélectionnées correspondent uniquement à des périodes de fermeture."
            )
            reporter.error(message)
            reporter.summary = message
            reporter.finalise(0)
            raise ValueError(message)
    elif closed_days:
        allowed_days = {
            day
            for day in daterange(schedule_start, schedule_end)
            if day not in closed_days
        }
        if not allowed_days:
            message = (
                "La fenêtre de planification est entièrement couverte par des périodes de fermeture."
            )
            reporter.error(message)
            reporter.summary = message
            reporter.finalise(0)
            raise ValueError(message)

    if normalised_weeks:
        candidate_days = (
            {day for day in allowed_days if day.weekday() < 5}
            if allowed_days is not None
            else set()
        )
        week_occurrences = sorted({_week_start_for(day) for day in candidate_days})
        if week_occurrences:
            effective_occurrences = len(week_occurrences)
        else:
            effective_occurrences = len({span_start for span_start, _ in normalised_weeks})
    else:
        effective_occurrences = course.sessions_required

    if not course.classes:
        message = "Associez au moins une classe au cours avant de planifier."
        reporter.error(message)
        reporter.summary = message
        reporter.finalise(0)
        raise ValueError(message)

    reporter.info(
        f"Durée cible des séances : {course.session_length_hours} h — "
        f"{effective_occurrences} occurrence(s) par groupe"
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
        total_required = effective_occurrences * course.session_length_hours
        already_scheduled = sum(existing_day_hours.values())
        hours_remaining = max(total_required - already_scheduled, 0)
        progress.initialise(hours_remaining)
        reporter.info(
            f"Heures requises : {total_required} h — déjà planifiées : {already_scheduled} h"
        )
        if hours_remaining == 0:
            for group in class_groups:
                _report_one_hour_alignment(
                    course=course,
                    class_group=group,
                    reporter=reporter,
                    pending_sessions=created_sessions,
                )
            reporter.info("Toutes les heures requises sont déjà planifiées.")
            progress.complete("Toutes les heures requises sont déjà planifiées.")
            reporter.finalise(len(created_sessions))
            return created_sessions
        available_days = [
            day
            for day in sorted(daterange(schedule_start, schedule_end))
            if day.weekday() < 5
            and all(group.is_available_on(day) for group in class_groups)
            and (allowed_days is None or day in allowed_days)
        ]
        if not available_days:
            message = (
                "Aucune journée commune disponible pour les classes sélectionnées"
            )
            reporter.error(message)
            placement_failures.append(message)
        else:
            per_day_hours = {day: existing_day_hours.get(day, 0) for day in available_days}
            day_indices = {day: index for index, day in enumerate(available_days)}
            weekday_frequencies = _weekday_frequency_for_groups(
                course,
                class_groups,
                pending_sessions=created_sessions,
            )
            slot_length_hours = max(int(course.session_length_hours), 1)
            block_index = 0
            relocation_weeks: set[date] = set()
            primary_link = links[0] if links else None
            link_lookup = {
                link.class_group_id: link for link in links if link.class_group_id is not None
            }
            while hours_remaining > 0:
                blocks_total = max(
                    (hours_remaining + slot_length_hours - 1) // slot_length_hours,
                    1,
                )
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

                matching_sessions = _matching_sessions_for_groups(
                    course,
                    class_groups,
                    pending_sessions=created_sessions,
                    require_exact_attendees=True,
                )
                base_session = matching_sessions[0] if matching_sessions else None
                continuity_weekday = (
                    base_session.start_time.weekday() if base_session is not None else None
                )
                continuity_slot_index: int | None = None
                if base_session is not None:
                    try:
                        continuity_slot_index = START_TIMES.index(
                            base_session.start_time.time()
                        )
                    except ValueError:
                        continuity_slot_index = None
                continuity_target_date: date | None = None
                if base_session is not None:
                    base_date = base_session.start_time.date()
                    week_offsets = [
                        max(0, (session.start_time.date() - base_date).days // 7)
                        for session in matching_sessions
                        if session.start_time.date() >= base_date
                    ]
                    next_offset = max(week_offsets, default=0) + 1
                    continuity_target_date = base_date + timedelta(days=7 * next_offset)

                def _cm_day_sort_key(d: date) -> tuple[int, int, int, int, int, int, int]:
                    anchor_distance = abs(day_indices[d] - anchor_index)
                    continuity_flag = 1
                    future_bias = 0
                    continuity_distance = anchor_distance
                    if continuity_weekday is not None and d.weekday() == continuity_weekday:
                        continuity_flag = 0
                        if continuity_target_date is not None:
                            future_bias = 0 if d >= continuity_target_date else 1
                            continuity_distance = abs((d - continuity_target_date).days)
                        else:
                            continuity_distance = 0
                    return (
                        continuity_flag,
                        future_bias,
                        continuity_distance,
                        -weekday_frequencies.get(d.weekday(), 0),
                        per_day_hours[d],
                        anchor_distance,
                        day_indices[d],
                    )

                ordered_days = sorted(available_days, key=_cm_day_sort_key)

                chronology_weeks: set[date] = set()
                weekly_limit_weeks: dict[str, set[date]] = defaultdict(set)

                def _attempt_day(day: date) -> bool:
                    nonlocal hours_remaining, block_index
                    week_start, _ = _week_bounds(day)
                    conflict_detected = False
                    for group in class_groups:
                        if has_weekly_course_conflict(
                            course,
                            group,
                            day,
                            pending_sessions=created_sessions,
                            additional_hours=desired_hours,
                        ):
                            link = link_lookup.get(group.id) if link_lookup else None
                            label = format_class_label(group, link=link)
                            weekly_limit_weeks[label].add(week_start)
                            conflict_detected = True
                    if conflict_detected:
                        return False
                    if not all(
                        _day_respects_chronology(
                            course, group, day, created_sessions, subgroup_label=None
                        )
                        for group in class_groups
                    ):
                        chronology_weeks.add(week_start)
                        return False
                    preferred_offsets: list[int] = []
                    if (
                        continuity_slot_index is not None
                        and continuity_weekday is not None
                        and day.weekday() == continuity_weekday
                    ):
                        preferred_offsets.append(continuity_slot_index)
                    if desired_hours == 1:
                        adjacency_offsets = _one_hour_adjacency_offsets(
                            class_groups,
                            day,
                            pending_sessions=created_sessions,
                            subgroup_label=None,
                        )
                        for offset in adjacency_offsets:
                            if offset not in preferred_offsets:
                                preferred_offsets.append(offset)
                    preferred_slot = _preferred_slot_index_for_groups(
                        course,
                        class_groups,
                        day,
                        pending_sessions=created_sessions,
                        subgroup_label=None,
                    )
                    if preferred_slot is not None and preferred_slot not in preferred_offsets:
                        preferred_offsets.append(preferred_slot)
                    fallback_offset = int(per_day_hours[day])
                    if fallback_offset not in preferred_offsets:
                        preferred_offsets.append(fallback_offset)

                    for base_offset in preferred_offsets:
                        block_sessions = _cm_schedule_block_for_day(
                            course=course,
                            class_groups=class_groups,
                            primary_link=primary_link,
                            day=day,
                            desired_hours=desired_hours,
                            base_offset=base_offset,
                            pending_sessions=created_sessions,
                            reporter=reporter,
                        )
                        if not block_sessions:
                            continue
                        created_sessions.extend(block_sessions)
                        block_hours = sum(session.duration_hours for session in block_sessions)
                        if block_hours > 0:
                            progress.record(block_hours, sessions=len(block_sessions))
                        for session in block_sessions:
                            reporter.session_created(session)
                            weekday_frequencies[session.start_time.weekday()] += 1
                        per_day_hours[day] += block_hours
                        hours_remaining = max(hours_remaining - block_hours, 0)
                        block_index += 1
                        return True
                    return False

                placed = False
                if (
                    continuity_target_date is not None
                    and continuity_target_date in available_days
                ):
                    placed = _attempt_day(continuity_target_date)

                if not placed:
                    for day in ordered_days:
                        if (
                            continuity_target_date is not None
                            and day == continuity_target_date
                        ):
                            continue
                        if _attempt_day(day):
                            placed = True
                            break

                if not placed:
                    cm_context = GlobalSearchContext(
                        course=course,
                        groups=class_groups,
                        available_days=available_days,
                        day_indices=day_indices,
                        slot_length_hours=slot_length_hours,
                        subgroup_label=None,
                        schedule_callable=partial(
                            _cm_schedule_block_for_day,
                            course=course,
                            class_groups=class_groups,
                            primary_link=primary_link,
                        ),
                        require_exact_attendees=True,
                    )
                    beam_plan = _beam_search_plan(
                        context=cm_context,
                        created_sessions=created_sessions,
                        per_day_hours=per_day_hours,
                        weekday_frequencies=weekday_frequencies,
                        hours_remaining=hours_remaining,
                        block_index=block_index,
                    )
                    if beam_plan:
                        plan_failed = False
                        for decision in beam_plan:
                            block_sessions = _cm_schedule_block_for_day(
                                course=course,
                                class_groups=class_groups,
                                primary_link=primary_link,
                                day=decision.day,
                                desired_hours=decision.desired_hours,
                                base_offset=decision.base_offset,
                                pending_sessions=created_sessions,
                                reporter=reporter,
                            )
                            if not block_sessions:
                                plan_failed = True
                                break
                            created_sessions.extend(block_sessions)
                            block_hours = sum(
                                session.duration_hours for session in block_sessions
                            )
                            if block_hours > 0:
                                progress.record(
                                    block_hours, sessions=len(block_sessions)
                                )
                            for session in block_sessions:
                                reporter.session_created(session)
                                weekday_frequencies[
                                    session.start_time.weekday()
                                ] += 1
                            per_day_hours.setdefault(decision.day, 0)
                            per_day_hours[decision.day] += block_hours
                            hours_remaining = max(
                                hours_remaining - block_hours, 0
                            )
                            block_index += 1
                        if not plan_failed:
                            placed = True

                    def _simulate_cm_relocation() -> bool:
                        backup_created = list(created_sessions)
                        backup_day_hours = dict(per_day_hours)
                        backup_weekdays = Counter(weekday_frequencies)
                        nested = db.session.begin_nested()
                        try:
                            simulated_attempted = set(relocation_weeks)
                            relocated = _relocate_sessions_for_groups(
                                course=course,
                                class_groups=class_groups,
                                created_sessions=created_sessions,
                                per_day_hours=per_day_hours,
                                weekday_frequencies=weekday_frequencies,
                                reporter=None,
                                attempted_weeks=simulated_attempted,
                                require_exact_attendees=True,
                                context_label=", ".join(
                                    group.name for group in class_groups
                                ),
                            )
                            if not relocated:
                                return False
                            placement = _cm_schedule_block_for_day(
                                course=course,
                                class_groups=class_groups,
                                primary_link=primary_link,
                                day=day,
                                desired_hours=desired_hours,
                                base_offset=base_offset,
                                pending_sessions=created_sessions,
                                reporter=None,
                            )
                            return bool(placement)
                        finally:
                            nested.rollback()
                            created_sessions[:] = backup_created
                            per_day_hours.clear()
                            per_day_hours.update(backup_day_hours)
                            weekday_frequencies.clear()
                            weekday_frequencies.update(backup_weekdays)

                    relocation_executed = False
                    if _simulate_cm_relocation():
                        relocated_hours = _relocate_sessions_for_groups(
                            course=course,
                            class_groups=class_groups,
                            created_sessions=created_sessions,
                            per_day_hours=per_day_hours,
                            weekday_frequencies=weekday_frequencies,
                            reporter=reporter,
                            attempted_weeks=relocation_weeks,
                            require_exact_attendees=True,
                            context_label=", ".join(
                                group.name for group in class_groups
                            ),
                        )
                        if relocated_hours:
                            hours_remaining += relocated_hours
                            block_index = max(block_index - 1, 0)
                            relocation_executed = True
                    if relocation_executed:
                        pass
                    else:
                        _warn_weekly_limit(reporter, weekly_limit_weeks)
                        for week_start in sorted(chronology_weeks):
                            reporter.warning(
                                "Ordre CM → TD → TP impossible à respecter "
                                f"la semaine du {week_start.strftime('%d/%m/%Y')}"
                            )
                        break

            if hours_remaining > 0:
                message = (
                    "Impossible de planifier "
                    f"{hours_remaining} heure(s) supplémentaire(s) (cours magistral)"
                )
                reporter.error(message)
                placement_failures.append(message)
        if not placement_failures:
            for group in class_groups:
                _report_one_hour_alignment(
                    course=course,
                    class_group=group,
                    reporter=reporter,
                    pending_sessions=created_sessions,
                    link=link_lookup.get(group.id) if link_lookup else None,
                )
        reporter.info(f"Total de séances générées : {len(created_sessions)}")
        if placement_failures:
            unique_failures: list[str] = []
            seen_failures: set[str] = set()
            for failure in placement_failures:
                if failure not in seen_failures:
                    unique_failures.append(failure)
                    seen_failures.add(failure)
            summary = (
                "Impossible de générer automatiquement toutes les séances : "
                + " ; ".join(unique_failures)
            )
            reporter.error(summary)
            reporter.summary = summary
            reporter.finalise(len(created_sessions))
            raise ValueError(summary)
        progress.complete(
            f"{len(created_sessions)} séance(s) générée(s)"
        )
        reporter.finalise(len(created_sessions))
        return created_sessions
    hours_needed_map: dict[tuple[int, str | None], float] = {}
    total_hours_needed = 0.0
    for link in links:
        for subgroup_label in link.group_labels():
            amount = _class_hours_needed(
                course,
                link.class_group,
                subgroup_label,
                occurrences_goal=effective_occurrences,
            )
            hours_needed_map[(link.class_group_id, subgroup_label or None)] = amount
            total_hours_needed += max(amount, 0)
    progress.initialise(total_hours_needed)

    for link in links:
        class_group = link.class_group
        for subgroup_label in link.group_labels():
            hours_needed = hours_needed_map.get((class_group.id, subgroup_label or None), 0)
            if hours_needed == 0:
                continue
            available_days = [
                day
                for day in sorted(daterange(schedule_start, schedule_end))
                if day.weekday() < 5
                and class_group.is_available_on(day)
                and (allowed_days is None or day in allowed_days)
            ]
            if not available_days:
                message = (
                    f"Aucune journée disponible pour {class_group.name} sur la période"
                )
                reporter.error(message)
                placement_failures.append(message)
                continue

            existing_day_hours = _existing_hours_by_day(course, class_group, subgroup_label)
            day_indices = {day: index for index, day in enumerate(available_days)}
            per_day_hours = {
                day: existing_day_hours.get(day, 0) for day in available_days
            }
            weekday_frequencies = _weekday_frequency_for_groups(
                course,
                [class_group],
                pending_sessions=created_sessions,
                subgroup_label=subgroup_label,
            )
            block_index = 0
            hours_remaining = hours_needed
            relocation_weeks: set[date] = set()

            while hours_remaining > 0:
                blocks_total = max(
                    (hours_remaining + slot_length_hours - 1) // slot_length_hours,
                    1,
                )
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

                matching_sessions = _matching_sessions_for_groups(
                    course,
                    [class_group],
                    pending_sessions=created_sessions,
                    subgroup_label=subgroup_label,
                )
                base_session = matching_sessions[0] if matching_sessions else None
                continuity_weekday = (
                    base_session.start_time.weekday() if base_session is not None else None
                )
                continuity_slot_index: int | None = None
                if base_session is not None:
                    try:
                        continuity_slot_index = START_TIMES.index(
                            base_session.start_time.time()
                        )
                    except ValueError:
                        continuity_slot_index = None
                continuity_target_date: date | None = None
                if base_session is not None:
                    base_date = base_session.start_time.date()
                    week_offsets = [
                        max(0, (session.start_time.date() - base_date).days // 7)
                        for session in matching_sessions
                        if session.start_time.date() >= base_date
                    ]
                    next_offset = max(week_offsets, default=0) + 1
                    continuity_target_date = base_date + timedelta(days=7 * next_offset)

                def _day_sort_key(d: date) -> tuple[int, int, int, int, int, int, int]:
                    anchor_distance = abs(day_indices[d] - anchor_index)
                    continuity_flag = 1
                    future_bias = 0
                    continuity_distance = anchor_distance
                    if continuity_weekday is not None and d.weekday() == continuity_weekday:
                        continuity_flag = 0
                        if continuity_target_date is not None:
                            future_bias = 0 if d >= continuity_target_date else 1
                            continuity_distance = abs((d - continuity_target_date).days)
                        else:
                            continuity_distance = 0
                    return (
                        continuity_flag,
                        future_bias,
                        continuity_distance,
                        -weekday_frequencies.get(d.weekday(), 0),
                        per_day_hours[d],
                        anchor_distance,
                        day_indices[d],
                    )

                ordered_days = sorted(available_days, key=_day_sort_key)

                chronology_weeks: set[date] = set()
                weekly_limit_weeks: dict[str, set[date]] = defaultdict(set)

                def _candidate_base_offsets(day: date) -> list[int]:
                    offsets: list[int] = []
                    if (
                        continuity_slot_index is not None
                        and continuity_weekday is not None
                        and day.weekday() == continuity_weekday
                    ):
                        offsets.append(continuity_slot_index)
                    if desired_hours == 1:
                        adjacency_offsets = _one_hour_adjacency_offsets(
                            [class_group],
                            day,
                            pending_sessions=created_sessions,
                            subgroup_label=subgroup_label,
                        )
                        for offset in adjacency_offsets:
                            if offset not in offsets:
                                offsets.append(offset)
                    preferred_slot = _preferred_slot_index_for_groups(
                        course,
                        [class_group],
                        day,
                        pending_sessions=created_sessions,
                        subgroup_label=subgroup_label,
                    )
                    if preferred_slot is not None and preferred_slot not in offsets:
                        offsets.append(preferred_slot)
                    fallback_offset = int(per_day_hours[day])
                    if fallback_offset not in offsets:
                        offsets.append(fallback_offset)
                    return offsets

                def _attempt_day(day: date) -> bool:
                    nonlocal hours_remaining, block_index
                    week_start, _ = _week_bounds(day)
                    if has_weekly_course_conflict(
                        course,
                        class_group,
                        day,
                        subgroup_label=subgroup_label,
                        pending_sessions=created_sessions,
                        additional_hours=desired_hours,
                    ):
                        label = format_class_label(
                            class_group, link=link, subgroup_label=subgroup_label
                        )
                        weekly_limit_weeks[label].add(week_start)
                        return False
                    if not _day_respects_chronology(
                        course,
                        class_group,
                        day,
                        created_sessions,
                        subgroup_label=subgroup_label,
                    ):
                        week_start, _ = _week_bounds(day)
                        chronology_weeks.add(week_start)
                        return False
                    preferred_offsets: list[int] = []
                    if (
                        continuity_slot_index is not None
                        and continuity_weekday is not None
                        and day.weekday() == continuity_weekday
                    ):
                        preferred_offsets.append(continuity_slot_index)
                    if desired_hours == 1:
                        adjacency_offsets = _one_hour_adjacency_offsets(
                            [class_group],
                            day,
                            pending_sessions=created_sessions,
                            subgroup_label=subgroup_label,
                        )
                        for offset in adjacency_offsets:
                            if offset not in preferred_offsets:
                                preferred_offsets.append(offset)
                    preferred_slot = _preferred_slot_index_for_groups(
                        course,
                        [class_group],
                        day,
                        pending_sessions=created_sessions,
                        subgroup_label=subgroup_label,
                    )
                    if preferred_slot is not None and preferred_slot not in preferred_offsets:
                        preferred_offsets.append(preferred_slot)
                    fallback_offset = int(per_day_hours[day])
                    if fallback_offset not in preferred_offsets:
                        preferred_offsets.append(fallback_offset)

                    for base_offset in _candidate_base_offsets(day):
                        block_sessions = _schedule_block_for_day(
                            course=course,
                            class_group=class_group,
                            link=link,
                            subgroup_label=subgroup_label,
                            day=day,
                            desired_hours=desired_hours,
                            base_offset=base_offset,
                            pending_sessions=created_sessions,
                            reporter=reporter,
                        )
                        if not block_sessions:
                            continue
                        created_sessions.extend(block_sessions)
                        block_hours = sum(
                            session.duration_hours for session in block_sessions
                        )
                        if block_hours > 0:
                            progress.record(block_hours, sessions=len(block_sessions))
                        for session in block_sessions:
                            reporter.session_created(session)
                            weekday_frequencies[session.start_time.weekday()] += 1
                        per_day_hours[day] += block_hours
                        hours_remaining = max(hours_remaining - block_hours, 0)
                        block_index += 1
                        return True
                    return False

                placed = False
                if (
                    continuity_target_date is not None
                    and continuity_target_date in available_days
                ):
                    placed = _attempt_day(continuity_target_date)

                if not placed:
                    for day in ordered_days:
                        if (
                            continuity_target_date is not None
                            and day == continuity_target_date
                        ):
                            continue
                        if _attempt_day(day):
                            placed = True
                            break

                if not placed:
                    group_context = GlobalSearchContext(
                        course=course,
                        groups=[class_group],
                        available_days=available_days,
                        day_indices=day_indices,
                        slot_length_hours=slot_length_hours,
                        subgroup_label=subgroup_label,
                        schedule_callable=partial(
                            _schedule_block_for_day,
                            course=course,
                            class_group=class_group,
                            link=link,
                            subgroup_label=subgroup_label,
                        ),
                    )
                    beam_plan = _beam_search_plan(
                        context=group_context,
                        created_sessions=created_sessions,
                        per_day_hours=per_day_hours,
                        weekday_frequencies=weekday_frequencies,
                        hours_remaining=hours_remaining,
                        block_index=block_index,
                    )
                    if beam_plan:
                        plan_failed = False
                        for decision in beam_plan:
                            block_sessions = _schedule_block_for_day(
                                course=course,
                                class_group=class_group,
                                link=link,
                                subgroup_label=subgroup_label,
                                day=decision.day,
                                desired_hours=decision.desired_hours,
                                base_offset=decision.base_offset,
                                pending_sessions=created_sessions,
                                reporter=reporter,
                            )
                            if not block_sessions:
                                plan_failed = True
                                break
                            created_sessions.extend(block_sessions)
                            block_hours = sum(
                                session.duration_hours for session in block_sessions
                            )
                            if block_hours > 0:
                                progress.record(
                                    block_hours, sessions=len(block_sessions)
                                )
                            for session in block_sessions:
                                reporter.session_created(session)
                                weekday_frequencies[
                                    session.start_time.weekday()
                                ] += 1
                            per_day_hours.setdefault(decision.day, 0)
                            per_day_hours[decision.day] += block_hours
                            hours_remaining = max(
                                hours_remaining - block_hours, 0
                            )
                            block_index += 1
                        if not plan_failed:
                            placed = True

                if not placed:
                    successful_relocation_plan: (
                        tuple[bool, date, int] | None
                    ) = None

                    def _simulate_relocation_attempt() -> bool:
                        nonlocal successful_relocation_plan
                        backup_created = list(created_sessions)
                        backup_day_hours = dict(per_day_hours)
                        backup_weekdays = Counter(weekday_frequencies)

                        def _attempt(require_exact: bool) -> bool:
                            nested = db.session.begin_nested()
                            try:
                                simulated_attempted = set(relocation_weeks)
                                relocated = _relocate_sessions_for_groups(
                                    course=course,
                                    class_groups=[class_group],
                                    created_sessions=created_sessions,
                                    per_day_hours=per_day_hours,
                                    weekday_frequencies=weekday_frequencies,
                                    reporter=None,
                                    attempted_weeks=simulated_attempted,
                                    subgroup_label=subgroup_label,
                                    context_label=format_class_label(
                                        class_group,
                                        link=link,
                                        subgroup_label=subgroup_label,
                                    ),
                                    require_exact_attendees=require_exact,
                                )
                                if not relocated:
                                    return False
                                candidate_days: list[date] = []
                                if (
                                    continuity_target_date is not None
                                    and continuity_target_date in available_days
                                ):
                                    candidate_days.append(continuity_target_date)
                                for candidate_day in ordered_days:
                                    if (
                                        continuity_target_date is not None
                                        and candidate_day == continuity_target_date
                                    ):
                                        continue
                                    candidate_days.append(candidate_day)
                                for candidate_day in candidate_days:
                                    for base_offset in _candidate_base_offsets(candidate_day):
                                        placement = _schedule_block_for_day(
                                            course=course,
                                            class_group=class_group,
                                            link=link,
                                            subgroup_label=subgroup_label,
                                            day=candidate_day,
                                            desired_hours=desired_hours,
                                            base_offset=base_offset,
                                            pending_sessions=created_sessions,
                                            reporter=None,
                                        )
                                        if placement:
                                            successful_relocation_plan = (
                                                require_exact,
                                                candidate_day,
                                                base_offset,
                                            )
                                            return True
                                return False
                            finally:
                                nested.rollback()
                                created_sessions[:] = backup_created
                                per_day_hours.clear()
                                per_day_hours.update(backup_day_hours)
                                weekday_frequencies.clear()
                                weekday_frequencies.update(backup_weekdays)

                        for require_exact in (True, False):
                            if _attempt(require_exact):
                                return True
                        return False

                    relocation_executed = False
                    if _simulate_relocation_attempt() and successful_relocation_plan:
                        require_exact, candidate_day, base_offset = (
                            successful_relocation_plan
                        )
                        relocated_hours = _relocate_sessions_for_groups(
                            course=course,
                            class_groups=[class_group],
                            created_sessions=created_sessions,
                            per_day_hours=per_day_hours,
                            weekday_frequencies=weekday_frequencies,
                            reporter=reporter,
                            attempted_weeks=relocation_weeks,
                            subgroup_label=subgroup_label,
                            context_label=format_class_label(
                                class_group, link=link, subgroup_label=subgroup_label
                            ),
                            require_exact_attendees=require_exact,
                        )
                        if relocated_hours:
                            hours_remaining += relocated_hours
                            block_index = max(block_index - 1, 0)
                            block_sessions = _schedule_block_for_day(
                                course=course,
                                class_group=class_group,
                                link=link,
                                subgroup_label=subgroup_label,
                                day=candidate_day,
                                desired_hours=desired_hours,
                                base_offset=base_offset,
                                pending_sessions=created_sessions,
                                reporter=reporter,
                            )
                            if block_sessions:
                                created_sessions.extend(block_sessions)
                                block_hours = sum(
                                    session.duration_hours for session in block_sessions
                                )
                                if block_hours > 0:
                                    progress.record(
                                        block_hours, sessions=len(block_sessions)
                                    )
                                for session in block_sessions:
                                    reporter.session_created(session)
                                    weekday_frequencies[
                                        session.start_time.weekday()
                                    ] += 1
                                per_day_hours.setdefault(candidate_day, 0)
                                per_day_hours[candidate_day] += block_hours
                                hours_remaining = max(hours_remaining - block_hours, 0)
                                block_index += 1
                                relocation_executed = True
                    if relocation_executed:
                        pass
                    else:
                        _warn_weekly_limit(reporter, weekly_limit_weeks)
                        for week_start in sorted(chronology_weeks):
                            reporter.warning(
                                f"Chronologie CM → TD → TP impossible pour {class_group.name} "
                                f"sur la semaine du {week_start.strftime('%d/%m/%Y')}"
                            )
                        break

            if hours_remaining > 0:
                message = (
                    f"Impossible de planifier {hours_remaining} heure(s) pour {class_group.name}"
                )
                reporter.error(message)
                placement_failures.append(message)
    if not placement_failures:
        for link in links:
            class_group = link.class_group
            for subgroup_label in link.group_labels():
                _report_one_hour_alignment(
                    course=course,
                    class_group=class_group,
                    reporter=reporter,
                    pending_sessions=created_sessions,
                    link=link,
                    subgroup_label=subgroup_label,
                )
    reporter.info(f"Total de séances générées : {len(created_sessions)}")
    if placement_failures:
        unique_failures = []
        seen_failures: set[str] = set()
        for failure in placement_failures:
            if failure not in seen_failures:
                unique_failures.append(failure)
                seen_failures.add(failure)
        summary = (
            "Impossible de générer automatiquement toutes les séances : "
            + " ; ".join(unique_failures)
        )
        reporter.error(summary)
        reporter.summary = summary
        reporter.finalise(len(created_sessions))
        raise ValueError(summary)
    progress.complete(f"{len(created_sessions)} séance(s) générée(s)")
    reporter.finalise(len(created_sessions))
    return created_sessions
