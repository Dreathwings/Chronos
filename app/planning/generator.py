from __future__ import annotations

import logging
import time as time_module
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from itertools import product
from math import ceil
from typing import Iterable, Iterator

from flask import current_app
from sqlalchemy.exc import IntegrityError

from app import db
from app.models import ClassGroup, ClosingPeriod, Course, CourseClassLink, Room, Session, Teacher
from app.planning.constants import START_TIMES, slot_range_for_segments
from app.planning.constraints import (
    ReasonCode,
    SessionRequest,
    available_teachers,
    can_place,
    ordered_rooms,
)
from app.planning.reporting import (
    ScheduleReporter,
    suggest_schedule_recovery,
    summarise_constraint_reasons,
)
from app.planning.utils import daterange, overlaps, week_bounds, week_start_for
from app.progress import NullScheduleProgress, ScheduleProgress


@dataclass(frozen=True)
class PlannedSession:
    course: Course
    teacher: Teacher
    room: Room
    class_group: ClassGroup
    start_time: datetime
    end_time: datetime
    subgroup_label: str | None
    attendees: list[ClassGroup]

    @property
    def teacher_id(self) -> int | None:
        return self.teacher.id

    @property
    def room_id(self) -> int | None:
        return getattr(self.room, "id", None)

    @property
    def class_group_id(self) -> int | None:
        return self.class_group.id

    @property
    def duration_hours(self) -> int:
        delta = self.end_time - self.start_time
        return max(int(delta.total_seconds() // 3600), 0)


@dataclass(frozen=True)
class Candidate:
    segments: list[tuple[datetime, datetime]]
    teachers: list[Teacher]
    rooms_by_segment: list[list[object]]
    slot_index: int


class AllocationState:
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

    def consume(self, teacher_id: int | None, duration_hours: float) -> float | None:
        if teacher_id is None or teacher_id not in self.remaining:
            return None
        previous = self.remaining[teacher_id]
        self.remaining[teacher_id] = max(
            self.remaining[teacher_id] - max(duration_hours, 0.0),
            0.0,
        )
        return previous

    def restore(self, teacher_id: int | None, previous: float | None) -> None:
        if teacher_id is None or previous is None or teacher_id not in self.remaining:
            return
        self.remaining[teacher_id] = previous


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


def _effective_occurrences(
    course: Course,
    *,
    schedule_start: date,
    schedule_end: date,
    allowed_days: set[date] | None,
    weekly_targets: dict[date, int],
    fallback_weekly_goal: int,
) -> int:
    if weekly_targets:
        available_week_count = len(weekly_targets)
        total_weekly_goal = sum(weekly_targets.values())
    else:
        candidate_days = (
            {day for day in allowed_days if day.weekday() < 5}
            if allowed_days is not None
            else {
                day
                for day in daterange(schedule_start, schedule_end)
                if day.weekday() < 5
            }
        )
        available_week_count = len({week_start_for(day) for day in candidate_days}) or 1
        total_weekly_goal = fallback_weekly_goal * available_week_count
    return max(int(course.sessions_required or 0), total_weekly_goal, 1)


def _segment_lengths(duration_hours: int) -> list[list[int]]:
    if duration_hours <= 1:
        return [[duration_hours]]
    if duration_hours == 4:
        return [[2, 2], [1, 1, 1, 1]]
    return [[duration_hours], [1] * duration_hours]


def _iter_candidate_segments(
    day: date, duration_hours: int
) -> Iterator[tuple[list[tuple[datetime, datetime]], int]]:
    for segment_lengths in _segment_lengths(duration_hours):
        segment_count = sum(segment_lengths)
        for start_index in range(len(START_TIMES) - segment_count + 1):
            segments = slot_range_for_segments(day, segment_lengths, start_index)
            if not segments:
                continue
            yield segments, start_index


def _sessions_for_day(
    class_group: ClassGroup,
    day: date,
    *,
    pending_sessions: Iterable[PlannedSession],
    subgroup_label: str | None = None,
) -> list[PlannedSession | Session]:
    target_label = (subgroup_label or "").strip().upper() or None
    collected: list[PlannedSession | Session] = []
    seen: set[int] = set()
    for collection in (class_group.all_sessions, list(pending_sessions)):
        for session in collection:
            marker = getattr(session, "id", None) or id(session)
            if marker in seen:
                continue
            seen.add(marker)
            if not _session_involves_class(session, class_group):
                continue
            session_label = (getattr(session, "subgroup_label", None) or "").strip().upper() or None
            if target_label is not None and session_label and session_label != target_label:
                continue
            if session.start_time.date() != day:
                continue
            collected.append(session)
    return sorted(collected, key=lambda s: s.start_time)


def _session_involves_class(session: PlannedSession | Session, class_group: ClassGroup) -> bool:
    if session.class_group_id == class_group.id:
        return True
    attendees = getattr(session, "attendees", []) or []
    return any(att.id == class_group.id for att in attendees)


def _teacher_hours(course: Course, pending_sessions: Iterable[PlannedSession]) -> dict[int, int]:
    totals: dict[int, int] = {}
    for session in course.sessions:
        if session.teacher_id is None:
            continue
        totals[session.teacher_id] = totals.get(session.teacher_id, 0) + session.duration_hours
    for session in pending_sessions:
        if session.teacher_id is None:
            continue
        totals[session.teacher_id] = totals.get(session.teacher_id, 0) + session.duration_hours
    return totals


def _warn_non_consecutive_one_hour_sessions(
    course: Course,
    reporter: ScheduleReporter,
    *,
    pending_sessions: Iterable[PlannedSession] = (),
) -> None:
    if course.session_length_hours != 1:
        return
    for link in course.class_links:
        class_group = link.class_group
        sessions_by_day: dict[date, list[Session | PlannedSession]] = {}
        for session in list(course.sessions) + list(pending_sessions):
            if session.duration_hours != 1:
                continue
            if not _session_involves_class(session, class_group):
                continue
            day = session.start_time.date()
            sessions_by_day.setdefault(day, []).append(session)
        for day, sessions in sessions_by_day.items():
            if len(sessions) <= 1:
                continue
            ordered = sorted(sessions, key=lambda s: s.start_time)
            violation = False
            for prev, nxt in zip(ordered, ordered[1:]):
                if nxt.start_time != prev.end_time:
                    violation = True
                    break
            if violation:
                reporter.warning(
                    "Séances d'1 h non consécutives détectées pour "
                    f"{course.name} — {class_group.name} le {day.strftime('%d/%m/%Y')}"
                )


def _score_candidate(
    request: SessionRequest,
    *,
    segments: list[tuple[datetime, datetime]],
    teacher: Teacher,
    rooms: list[object],
    pending_sessions: list[PlannedSession],
    weekly_targets: dict[date, int],
) -> float:
    day = segments[0][0].date()
    slot_index = 0
    try:
        slot_index = START_TIMES.index(segments[0][0].time())
    except ValueError:
        slot_index = len(START_TIMES)
    score = slot_index * 0.8

    room_ids = [getattr(room, "id", None) for room in rooms]
    if len(set(room_ids)) > 1:
        score += 1.0 * (len(room_ids) - 1)

    for group in request.class_groups:
        sessions_today = _sessions_for_day(
            group,
            day,
            pending_sessions=pending_sessions,
            subgroup_label=request.subgroup_label,
        )
        simulated_sessions = list(sessions_today)
        for idx, segment in enumerate(segments):
            simulated_sessions.append(
                PlannedSession(
                    course=request.course,
                    teacher=teacher,
                    room=rooms[idx],
                    class_group=group,
                    start_time=segment[0],
                    end_time=segment[1],
                    subgroup_label=request.subgroup_label,
                    attendees=request.class_groups,
                )
            )
        simulated_sessions.sort(key=lambda s: s.start_time)
        for prev, nxt in zip(simulated_sessions, simulated_sessions[1:]):
            gap = (nxt.start_time - prev.end_time).total_seconds() / 3600.0
            if gap > 0.01:
                score += gap * 1.5
        for prev, nxt in zip(simulated_sessions, simulated_sessions[1:]):
            if prev.end_time == nxt.start_time and prev.room_id != nxt.room_id:
                score += 0.5
        if request.duration_hours == 1:
            for session in sessions_today:
                if session.end_time == segments[0][0] or session.start_time == segments[0][1]:
                    score -= 3.0

        if weekly_targets:
            week_start, _ = week_bounds(day)
            weekly_goal = weekly_targets.get(week_start)
            if weekly_goal:
                week_sessions = 0
                for session in group.all_sessions:
                    session_week_start, _ = week_bounds(session.start_time.date())
                    if session_week_start == week_start:
                        week_sessions += session.duration_hours
                for session in pending_sessions:
                    session_week_start, _ = week_bounds(session.start_time.date())
                    if session_week_start == week_start and _session_involves_class(session, group):
                        week_sessions += session.duration_hours
                if week_sessions + request.duration_hours > weekly_goal * request.course.session_length_hours:
                    score += 2.0

    teacher_hours = _teacher_hours(request.course, pending_sessions)
    if request.course.teachers:
        average_hours = sum(teacher_hours.values()) / max(len(request.course.teachers), 1)
        score += max((teacher_hours.get(teacher.id or 0, 0) + request.duration_hours) - average_hours, 0) * 0.2
    return score


def _build_requests(
    course: Course,
    *,
    effective_occurrences: int,
) -> list[SessionRequest]:
    requests: list[SessionRequest] = []
    links = sorted(course.class_links, key=lambda link: link.class_group.name.lower())
    if not links:
        return requests
    if course.is_cm:
        class_groups = [link.class_group for link in links]
        total_required = effective_occurrences * course.session_length_hours
        target_ids = {group.id for group in class_groups if group.id}
        already_scheduled = 0
        for session in course.sessions:
            if session.attendee_ids() == target_ids:
                already_scheduled += session.duration_hours
        remaining = max(total_required - already_scheduled, 0)
        primary_link = links[0]
        while remaining > 0:
            duration = min(course.session_length_hours, remaining)
            requests.append(
                SessionRequest(
                    course=course,
                    class_groups=class_groups,
                    subgroup_label=None,
                    duration_hours=int(duration),
                    link=None,
                    primary_link=primary_link,
                )
            )
            remaining = max(remaining - duration, 0)
        return requests

    for link in links:
        class_group = link.class_group
        for subgroup_label in link.group_labels():
            existing = sum(
                session.duration_hours
                for session in course.sessions
                if session.class_group_id == class_group.id
                and (session.subgroup_label or "").upper() == (subgroup_label or "").upper()
            )
            required_total = effective_occurrences * course.session_length_hours
            remaining = max(required_total - existing, 0)
            while remaining > 0:
                duration = min(course.session_length_hours, remaining)
                requests.append(
                    SessionRequest(
                        course=course,
                        class_groups=[class_group],
                        subgroup_label=subgroup_label,
                        duration_hours=int(duration),
                        link=link,
                        primary_link=None,
                    )
                )
                remaining = max(remaining - duration, 0)
    return requests


def _build_candidates(
    request: SessionRequest,
    *,
    allowed_days: Iterable[date],
    allocation_state: AllocationState,
) -> list[Candidate]:
    candidates: list[Candidate] = []
    class_groups = request.class_groups
    target_class_ids = {group.id for group in class_groups if group.id}
    teacher_pool = available_teachers(
        request.course,
        link=request.link or request.primary_link,
        subgroup_label=request.subgroup_label,
        allocation_state=allocation_state,
        target_class_ids=target_class_ids or None,
    )
    if not teacher_pool:
        return candidates
    room_pool = ordered_rooms(request.course)
    if not room_pool:
        return candidates

    for day in sorted(allowed_days):
        if day.weekday() >= 5:
            continue
        if not all(group.is_available_on(day) for group in class_groups):
            continue
        for segments, start_index in _iter_candidate_segments(day, request.duration_hours):
            if not all(
                group.is_available_during(
                    segment_start,
                    segment_end,
                    subgroup_label=request.subgroup_label,
                )
                for group in class_groups
                for segment_start, segment_end in segments
            ):
                continue
            available_teachers_for_segments = [
                teacher
                for teacher in teacher_pool
                if all(teacher.is_available_during(start, end) for start, end in segments)
                and not any(
                    overlaps(existing.start_time, existing.end_time, start, end)
                    for existing in teacher.sessions
                    for start, end in segments
                )
            ]
            if not available_teachers_for_segments:
                continue
            rooms_by_segment: list[list[object]] = []
            for start, end in segments:
                rooms_for_segment = [
                    room
                    for room in room_pool
                    if not any(
                        overlaps(existing.start_time, existing.end_time, start, end)
                        for existing in room.sessions
                    )
                ]
                rooms_by_segment.append(rooms_for_segment)
            if not rooms_by_segment or any(not rooms for rooms in rooms_by_segment):
                continue
            candidates.append(
                Candidate(
                    segments=segments,
                    teachers=available_teachers_for_segments,
                    rooms_by_segment=rooms_by_segment,
                    slot_index=start_index,
                )
            )
    return candidates


def _filter_rooms_for_pending(
    rooms_by_segment: list[list[object]],
    segments: list[tuple[datetime, datetime]],
    pending_sessions: list[PlannedSession],
) -> list[list[object]]:
    filtered: list[list[object]] = []
    for rooms, (start, end) in zip(rooms_by_segment, segments):
        available = [
            room
            for room in rooms
            if not any(
                room.id == session.room_id
                and overlaps(session.start_time, session.end_time, start, end)
                for session in pending_sessions
            )
        ]
        filtered.append(available)
    return filtered


def _filter_teachers_for_pending(
    teachers: list[Teacher],
    segments: list[tuple[datetime, datetime]],
    pending_sessions: list[PlannedSession],
    allocation_state: AllocationState,
    duration_hours: int,
) -> list[Teacher]:
    candidates: list[Teacher] = []
    for teacher in teachers:
        if not allocation_state.can_allocate(teacher.id, float(duration_hours)):
            continue
        if any(
            teacher.id == session.teacher_id
            and overlaps(session.start_time, session.end_time, start, end)
            for session in pending_sessions
            for start, end in segments
        ):
            continue
        if not all(teacher.is_available_during(start, end) for start, end in segments):
            continue
        candidates.append(teacher)
    return candidates


def _candidate_room_combinations(
    rooms_by_segment: list[list[object]],
    segment_count: int,
    max_combinations: int,
) -> list[list[object]]:
    if not rooms_by_segment:
        return []
    intersected_ids = {getattr(room, "id", None) for room in rooms_by_segment[0]}
    for rooms in rooms_by_segment[1:]:
        intersected_ids &= {getattr(room, "id", None) for room in rooms}
    if intersected_ids:
        shared = [
            room
            for room in rooms_by_segment[0]
            if getattr(room, "id", None) in intersected_ids
        ]
        return [[room] * segment_count for room in shared]
    combos = []
    for combo in product(*rooms_by_segment):
        combos.append(list(combo))
        if len(combos) >= max_combinations:
            break
    return combos


def _reason_label(code: ReasonCode) -> str:
    labels = {
        ReasonCode.CLASS_UNAVAILABLE: "Classe indisponible",
        ReasonCode.CLASS_CONFLICT: "Classe déjà planifiée",
        ReasonCode.TEACHER_UNAVAILABLE: "Enseignant indisponible",
        ReasonCode.TEACHER_CONFLICT: "Enseignant déjà planifié",
        ReasonCode.TEACHER_ALLOCATION: "Quota enseignant dépassé",
        ReasonCode.ROOM_CAPACITY: "Salle trop petite",
        ReasonCode.ROOM_COMPUTERS: "Postes informatiques insuffisants",
        ReasonCode.ROOM_EQUIPMENT: "Équipements requis manquants",
        ReasonCode.ROOM_SOFTWARE: "Logiciels requis manquants",
        ReasonCode.ROOM_CONFLICT: "Salle déjà occupée",
        ReasonCode.ROOM_UNAVAILABLE: "Salle indisponible",
        ReasonCode.CHRONOLOGY: "Chronologie CM → TD → TP",
        ReasonCode.WEEKLY_LIMIT: "Limite hebdomadaire",
    }
    return labels.get(code, code.value)


def generate_schedule(
    course: Course,
    *,
    window_start: date | None = None,
    window_end: date | None = None,
    allowed_weeks: Iterable[tuple[date, date, int]] | None = None,
    progress: ScheduleProgress | None = None,
) -> list[Session]:
    progress = progress or NullScheduleProgress()
    reporter = ScheduleReporter(course)
    created_sessions: list[Session] = []
    allocation_state = AllocationState(course)
    logger = getattr(current_app, "logger", logging.getLogger(__name__))
    total_start = time_module.monotonic()
    reason_counts: Counter[str] = Counter()

    try:
        schedule_start, schedule_end = _resolve_schedule_window(
            course, window_start, window_end
        )
    except ValueError as exc:
        reporter.error(str(exc), suggestions=suggest_schedule_recovery(str(exc), course))
        reporter.summary = str(exc)
        reporter.finalise(0)
        raise

    fallback_weekly_goal = max(int(course.sessions_per_week or 0), 0)
    weekly_targets: dict[date, int] = {}
    normalised_weeks: list[tuple[date, date]] = []
    if allowed_weeks:
        for entry in allowed_weeks:
            if entry is None or not isinstance(entry, (list, tuple)):
                continue
            if len(entry) < 2:
                continue
            week_start, week_end = entry[0], entry[1]
            weekly_goal = entry[2] if len(entry) > 2 else None
            if week_start is None or week_end is None:
                continue
            if week_end < week_start:
                week_start, week_end = week_end, week_start
            canonical_start = week_start_for(week_start)
            try:
                goal_value = (
                    int(weekly_goal)
                    if weekly_goal is not None
                    else fallback_weekly_goal
                )
            except (TypeError, ValueError):
                goal_value = fallback_weekly_goal
            weekly_targets[canonical_start] = max(goal_value, 0)
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
            reporter.error(message, suggestions=suggest_schedule_recovery(message, course))
            reporter.summary = message
            reporter.finalise(0)
            raise ValueError(message)
        schedule_start = normalised_weeks[0][0]
        schedule_end = normalised_weeks[-1][1]
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
            reporter.info("Semaines exclues pour congés : " + removed_labels)
        if not allowed_days:
            message = (
                "Les semaines sélectionnées correspondent uniquement à des périodes de fermeture."
            )
            reporter.error(message, suggestions=suggest_schedule_recovery(message, course))
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
            reporter.error(message, suggestions=suggest_schedule_recovery(message, course))
            reporter.summary = message
            reporter.finalise(0)
            raise ValueError(message)

    effective_occurrences = _effective_occurrences(
        course,
        schedule_start=schedule_start,
        schedule_end=schedule_end,
        allowed_days=allowed_days,
        weekly_targets=weekly_targets,
        fallback_weekly_goal=fallback_weekly_goal,
    )

    if not course.classes:
        message = "Associez au moins une classe au cours avant de planifier."
        reporter.error(message, suggestions=suggest_schedule_recovery(message, course))
        reporter.summary = message
        reporter.finalise(0)
        raise ValueError(message)

    requests = _build_requests(course, effective_occurrences=effective_occurrences)
    if not requests:
        reporter.info("Toutes les heures requises sont déjà planifiées.")
        _warn_non_consecutive_one_hour_sessions(course, reporter)
        progress.complete("Toutes les heures requises sont déjà planifiées.")
        reporter.finalise(0)
        return []

    total_hours = sum(request.duration_hours for request in requests)
    progress.initialise(total_hours)

    if allowed_days is None:
        allowed_days = {
            day
            for day in daterange(schedule_start, schedule_end)
            if day.weekday() < 5 and day not in closed_days
        }
    if allowed_days and len(allowed_days) > 150:
        day_list = sorted(allowed_days)
        sample_target = max(effective_occurrences * 10, 60)
        if len(day_list) > sample_target:
            step = max(len(day_list) // sample_target, 1)
            allowed_days = set(day_list[::step])

    candidate_map: dict[int, list[Candidate]] = {}
    for idx, request in enumerate(requests):
        candidates = _build_candidates(
            request, allowed_days=allowed_days, allocation_state=allocation_state
        )
        candidate_map[idx] = candidates
        reporter.info(
            f"{len(candidates)} candidat(s) pour {request.course.name} — "
            f"{', '.join(group.name for group in request.class_groups)}"
        )

    time_limit = float(current_app.config.get("SCHEDULE_SEARCH_TIME_LIMIT", 2.0))
    iteration_limit = int(current_app.config.get("SCHEDULE_SEARCH_ITERATION_LIMIT", 5000))
    allow_partial = bool(current_app.config.get("SCHEDULE_ALLOW_PARTIAL_COMMIT", False))

    best_plan: list[PlannedSession] = []
    best_score = float("inf")
    iterations = 0
    total_hours_required = sum(request.duration_hours for request in requests)
    search_start = time_module.monotonic()

    def search(
        remaining: list[int],
        pending_sessions: list[PlannedSession],
        cumulative_score: float,
    ) -> None:
        nonlocal best_plan, best_score, iterations
        if time_module.monotonic() - search_start > time_limit:
            return
        iterations += 1
        if iterations > iteration_limit:
            return
        if not remaining:
            planned_hours = sum(session.duration_hours for session in pending_sessions)
            best_hours = sum(session.duration_hours for session in best_plan)
            if planned_hours > best_hours or (
                planned_hours == best_hours and cumulative_score < best_score
            ):
                best_plan = list(pending_sessions)
                best_score = cumulative_score
            return

        best_request_idx = None
        best_options: list[tuple[int, Candidate, list[Teacher], list[list[object]]]] = []
        smallest = float("inf")
        for request_idx in remaining:
            request = requests[request_idx]
            options: list[tuple[int, Candidate, list[Teacher], list[list[object]]]] = []
            for candidate in candidate_map[request_idx]:
                filtered_teachers = _filter_teachers_for_pending(
                    candidate.teachers,
                    candidate.segments,
                    pending_sessions,
                    allocation_state,
                    request.duration_hours,
                )
                if not filtered_teachers:
                    continue
                filtered_rooms_by_segment = _filter_rooms_for_pending(
                    candidate.rooms_by_segment, candidate.segments, pending_sessions
                )
                if any(not rooms for rooms in filtered_rooms_by_segment):
                    continue
                option_count = len(filtered_teachers) * max(
                    min(len(rooms) for rooms in filtered_rooms_by_segment), 1
                )
                options.append(
                    (option_count, candidate, filtered_teachers, filtered_rooms_by_segment)
                )
            if not options:
                continue
            option_min = min(option[0] for option in options)
            if option_min < smallest:
                smallest = option_min
                best_request_idx = request_idx
                best_options = options

        if best_request_idx is None:
            return

        request = requests[best_request_idx]
        scored_candidates: list[tuple[float, Candidate, list[Teacher], list[list[object]]]] = []
        for _, candidate, teachers, rooms_by_segment in best_options:
            scored_candidates.append((candidate.slot_index, candidate, teachers, rooms_by_segment))
        scored_candidates.sort(key=lambda item: item[0])

        for _, candidate, teachers, rooms_by_segment in scored_candidates:
            room_combos = _candidate_room_combinations(
                rooms_by_segment, len(candidate.segments), max_combinations=20
            )
            scored_options: list[tuple[float, Teacher, list[object]]] = []
            for teacher in teachers:
                for rooms in room_combos:
                    violations = can_place(
                        request,
                        teacher=teacher,
                        rooms=rooms,
                        segments=candidate.segments,
                        pending_sessions=pending_sessions,
                        allocation_state=allocation_state,
                        weekly_targets=weekly_targets,
                    )
                    if violations:
                        for violation in violations:
                            reason_counts[_reason_label(violation.code)] += 1
                        continue
                    score = _score_candidate(
                        request,
                        segments=candidate.segments,
                        teacher=teacher,
                        rooms=rooms,
                        pending_sessions=pending_sessions,
                        weekly_targets=weekly_targets,
                    )
                    scored_options.append((score, teacher, rooms))
            scored_options.sort(key=lambda item: item[0])
            for score, teacher, rooms in scored_options:
                projected_score = cumulative_score + score
                if projected_score >= best_score and best_plan:
                    continue
                previous = allocation_state.consume(teacher.id, float(request.duration_hours))
                planned: list[PlannedSession] = []
                for (segment_start, segment_end), room in zip(candidate.segments, rooms):
                    planned.append(
                        PlannedSession(
                            course=request.course,
                            teacher=teacher,
                            room=room,
                            class_group=request.primary_class or request.class_groups[0],
                            start_time=segment_start,
                            end_time=segment_end,
                            subgroup_label=request.subgroup_label,
                            attendees=list(request.class_groups),
                        )
                    )
                pending_sessions.extend(planned)
                planned_hours = sum(session.duration_hours for session in pending_sessions)
                best_hours = sum(session.duration_hours for session in best_plan)
                if planned_hours > best_hours or (
                    planned_hours == best_hours and projected_score < best_score
                ):
                    best_plan = list(pending_sessions)
                    best_score = projected_score
                remaining_next = [idx for idx in remaining if idx != best_request_idx]
                search(remaining_next, pending_sessions, projected_score)
                for _ in range(len(planned)):
                    pending_sessions.pop()
                allocation_state.restore(teacher.id, previous)

    search(list(range(len(requests))), [], 0.0)

    total_candidates = sum(len(candidates) for candidates in candidate_map.values())
    planned_hours = sum(session.duration_hours for session in best_plan)
    if planned_hours < total_hours_required:
        greedy_state = AllocationState(course)
        greedy_plan: list[PlannedSession] = []
        request_order = sorted(
            range(len(requests)),
            key=lambda idx: len(candidate_map.get(idx, [])),
        )
        for request_idx in request_order:
            request = requests[request_idx]
            best_option: tuple[float, Candidate, Teacher, list[object]] | None = None
            for candidate in candidate_map[request_idx]:
                filtered_teachers = _filter_teachers_for_pending(
                    candidate.teachers,
                    candidate.segments,
                    greedy_plan,
                    greedy_state,
                    request.duration_hours,
                )
                if not filtered_teachers:
                    continue
                filtered_rooms_by_segment = _filter_rooms_for_pending(
                    candidate.rooms_by_segment, candidate.segments, greedy_plan
                )
                if any(not rooms for rooms in filtered_rooms_by_segment):
                    continue
                room_combos = _candidate_room_combinations(
                    filtered_rooms_by_segment, len(candidate.segments), max_combinations=10
                )
                for teacher in filtered_teachers:
                    for rooms in room_combos:
                        violations = can_place(
                            request,
                            teacher=teacher,
                            rooms=rooms,
                            segments=candidate.segments,
                            pending_sessions=greedy_plan,
                            allocation_state=greedy_state,
                            weekly_targets=weekly_targets,
                        )
                        if violations:
                            continue
                        score = _score_candidate(
                            request,
                            segments=candidate.segments,
                            teacher=teacher,
                            rooms=rooms,
                            pending_sessions=greedy_plan,
                            weekly_targets=weekly_targets,
                        )
                        if best_option is None or score < best_option[0]:
                            best_option = (score, candidate, teacher, rooms)
            if best_option is None:
                continue
            _, candidate, teacher, rooms = best_option
            greedy_state.consume(teacher.id, float(request.duration_hours))
            for (segment_start, segment_end), room in zip(candidate.segments, rooms):
                greedy_plan.append(
                    PlannedSession(
                        course=request.course,
                        teacher=teacher,
                        room=room,
                        class_group=request.primary_class or request.class_groups[0],
                        start_time=segment_start,
                        end_time=segment_end,
                        subgroup_label=request.subgroup_label,
                        attendees=list(request.class_groups),
                    )
                )
        greedy_hours = sum(session.duration_hours for session in greedy_plan)
        if greedy_hours > planned_hours:
            best_plan = greedy_plan
            planned_hours = greedy_hours
    elapsed = time_module.monotonic() - total_start
    logger.info(
        "Schedule generation for %s completed in %.2fs (%d iterations, %d/%d heures planifiées, %d candidats).",
        course.name,
        elapsed,
        iterations,
        planned_hours,
        total_hours_required,
        total_candidates,
    )

    if not best_plan:
        message = "Impossible de générer automatiquement toutes les séances."
        reporter.error(
            message,
            suggestions=suggest_schedule_recovery(message, course),
        )
        reason_labels = summarise_constraint_reasons(reason_counts)
        if reason_labels:
            reporter.warning(
                "Contraintes bloquantes principales : " + ", ".join(reason_labels)
            )
        reporter.summary = message
        reporter.finalise(0)
        raise ValueError(message)

    complete = planned_hours >= total_hours_required
    if not complete and not allow_partial:
        message = "Planification partielle : aucune séance n'a été enregistrée."
        reporter.error(
            message,
            suggestions=suggest_schedule_recovery(message, course),
        )
        reason_labels = summarise_constraint_reasons(reason_counts)
        if reason_labels:
            reporter.warning(
                "Contraintes bloquantes principales : " + ", ".join(reason_labels)
            )
        reporter.summary = message
        reporter.finalise(0)
        raise ValueError(message)

    try:
        with db.session.begin_nested():
            for planned in best_plan:
                session = Session(
                    course=planned.course,
                    teacher=planned.teacher,
                    room=planned.room,
                    class_group=planned.class_group,
                    subgroup_label=planned.subgroup_label,
                    start_time=planned.start_time,
                    end_time=planned.end_time,
                )
                session.attendees = list(planned.attendees)
                db.session.add(session)
                created_sessions.append(session)
            db.session.flush()
    except IntegrityError as exc:
        db.session.rollback()
        message = "Collision détectée lors de l'enregistrement des séances."
        logger.warning("Schedule generation conflict for %s: %s", course.name, exc)
        reporter.error(
            message,
            suggestions=suggest_schedule_recovery(message, course),
        )
        reporter.summary = message
        reporter.finalise(0)
        raise ValueError(message)

    for session in created_sessions:
        reporter.session_created(session)
        progress.record(session.duration_hours, sessions=1)

    _warn_non_consecutive_one_hour_sessions(
        course, reporter, pending_sessions=created_sessions
    )

    reason_labels = summarise_constraint_reasons(reason_counts)
    if reason_labels:
        reporter.info(
            "Contraintes bloquantes principales : " + ", ".join(reason_labels)
        )

    if not complete:
        message = (
            f"{len(created_sessions)} séance(s) créées — "
            "certaines séances n'ont pas pu être planifiées."
        )
        reporter.warning(
            message,
            suggestions=suggest_schedule_recovery(message, course),
        )
        reporter.summary = message
    else:
        reporter.info(f"Total de séances générées : {len(created_sessions)}")
    progress.complete(f"{len(created_sessions)} séance(s) générée(s)")
    reporter.finalise(len(created_sessions))
    return created_sessions
