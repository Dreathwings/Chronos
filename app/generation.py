from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Iterable, List, Sequence

from flask import current_app

from . import db
from .models import ClosingPeriod, Course
from .progress import ScheduleProgressTracker
from .scheduler import generate_schedule

COURSE_TYPE_ORDER: Sequence[str] = ("CM", "SAE", "Eval", "TD", "TP")


@dataclass
class CourseScheduleState:
    course: Course
    allowed_spans: List[tuple[date, date]] = field(default_factory=list)
    weekly_targets: dict[date, int] = field(default_factory=dict)
    pending_hours: int = 0
    failed: bool = False
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        if not self.allowed_spans:
            if self.course.allowed_weeks:
                self.allowed_spans = [entry.week_span for entry in self.course.allowed_weeks]
                self.weekly_targets = {
                    entry.week_start: entry.effective_sessions(self.course.sessions_per_week)
                    for entry in self.course.allowed_weeks
                }
            else:
                window = self.course.semester_window
                if window is None:
                    today = date.today()
                    window = (today, today + timedelta(days=12 * 7 - 1))
                self.allowed_spans = [window]
        self.refresh()

    def refresh(self) -> None:
        self.pending_hours = max(self.course.total_required_hours - self.course.scheduled_hours, 0)
        if self.pending_hours == 0:
            self.failed = False
            self.failure_reason = None

    @property
    def session_length(self) -> int:
        length = max(int(self.course.session_length_hours or 0), 0)
        return length or 1

    def occurrences_remaining(self) -> int:
        if self.pending_hours <= 0:
            return 0
        return math.ceil(self.pending_hours / self.session_length)

    def weekly_goal(self, week_start: date) -> int:
        remaining = self.occurrences_remaining()
        if remaining <= 0:
            return 0
        if week_start in self.weekly_targets:
            goal = self.weekly_targets[week_start]
        elif self.course.sessions_per_week:
            goal = int(self.course.sessions_per_week)
        else:
            goal = remaining
        return max(0, min(goal, remaining))

    def is_active_during(self, week_start: date, week_end: date) -> bool:
        for span_start, span_end in self.allowed_spans:
            if span_end < week_start or span_start > week_end:
                continue
            return True
        return False

    def mark_failed(self, reason: str | None) -> None:
        self.failed = True
        self.failure_reason = reason.strip() if reason else None


class WeeklyGenerationPlanner:
    def __init__(self, courses: Iterable[Course], tracker: ScheduleProgressTracker) -> None:
        self.tracker = tracker
        self.states = [CourseScheduleState(course) for course in courses]
        self.weeks = self._collect_weeks()

    def _collect_weeks(self) -> List[date]:
        week_starts: set[date] = set()
        for state in self.states:
            for span_start, span_end in state.allowed_spans:
                current = span_start - timedelta(days=span_start.weekday())
                week_end = current + timedelta(days=6)
                while week_end >= span_start and current <= span_end:
                    week_starts.add(current)
                    current += timedelta(days=7)
                    week_end = current + timedelta(days=6)
        return sorted(week_starts)

    def _closing_days_for_week(self, week_start: date, week_end: date) -> list[date]:
        closed: list[date] = []
        for period in ClosingPeriod.ordered_periods():
            if period.end_date < week_start or period.start_date > week_end:
                continue
            start = max(period.start_date, week_start)
            end = min(period.end_date, week_end)
            current = start
            while current <= end:
                closed.append(current)
                current += timedelta(days=1)
        return sorted(set(closed))

    def _state_sort_key(self, state: CourseScheduleState) -> tuple[int, str]:
        course_type = (state.course.course_type or "").upper()
        try:
            index = COURSE_TYPE_ORDER.index(course_type)
        except ValueError:
            index = len(COURSE_TYPE_ORDER)
        return index, state.course.name.lower()

    def run(self) -> tuple[int, list[str]]:
        total_created = 0
        errors: list[str] = []
        for week_start in self.weeks:
            week_end = week_start + timedelta(days=6)
            closed_days = self._closing_days_for_week(week_start, week_end)
            working_days = [
                week_start + timedelta(days=offset)
                for offset in range(5)
                if (week_start + timedelta(days=offset)) not in closed_days
            ]
            if not working_days:
                if closed_days and current_app:
                    current_app.logger.info(
                        "Semaine du %s ignorée : fermeture complète (jours : %s)",
                        week_start,
                        ", ".join(day.strftime("%d/%m/%Y") for day in closed_days),
                    )
                continue

            active_states = [
                state
                for state in self.states
                if not state.failed
                and state.pending_hours > 0
                and state.is_active_during(week_start, week_end)
            ]
            if not active_states:
                continue

            active_states.sort(key=self._state_sort_key)

            for state in active_states:
                weekly_goal = state.weekly_goal(week_start)
                if weekly_goal <= 0:
                    continue

                slice_label = (
                    f"{state.course.name} — semaine du {week_start.strftime('%d/%m/%Y')}"
                )
                slice_progress = self.tracker.create_slice(label=slice_label)
                target_hours = weekly_goal * state.session_length
                slice_progress.initialise(target_hours)

                try:
                    created_sessions = generate_schedule(
                        state.course,
                        window_start=week_start,
                        window_end=week_end,
                        allowed_weeks=[(week_start, week_end, weekly_goal)],
                        progress=slice_progress,
                        max_new_hours=target_hours,
                    )
                except ValueError as exc:
                    state.mark_failed(str(exc))
                    db.session.rollback()
                    errors.append(f"{state.course.name} : {exc}")
                    continue

                total_created += len(created_sessions)
                db.session.commit()
                state.refresh()

        for state in self.states:
            if state.pending_hours > 0 and not state.failed:
                remaining_occurrences = state.occurrences_remaining()
                if remaining_occurrences <= 0:
                    continue
                errors.append(
                    "{} : séances restantes hors fenêtre autorisée ({})".format(
                        state.course.name,
                        state.pending_hours,
                    )
                )

        return total_created, errors

