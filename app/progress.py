from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass
from typing import Dict, List


class ScheduleProgress:
    """Interface used by the scheduler to report progress."""

    def initialise(self, total_hours: float) -> None:  # pragma: no cover - interface
        """Initialise the expected workload."""

    def record(self, hours: float, sessions: int = 0) -> None:  # pragma: no cover
        """Record scheduled workload."""

    def complete(self, message: str | None = None) -> None:  # pragma: no cover
        """Mark the job as finished successfully."""

    def update_week_overview(
        self, week_label: str | None, entries: List[dict[str, object]]
    ) -> None:  # pragma: no cover - interface
        """Update the list of sessions generated for the active week."""


class NullScheduleProgress(ScheduleProgress):
    """Fallback progress adapter used when no tracking is requested."""

    def initialise(self, total_hours: float) -> None:
        return

    def record(self, hours: float, sessions: int = 0) -> None:
        return

    def complete(self, message: str | None = None) -> None:
        return

    def update_week_overview(
        self, week_label: str | None, entries: List[dict[str, object]]
    ) -> None:
        return


@dataclass
class ProgressSnapshot:
    job_id: str
    label: str
    state: str
    percent: int
    eta_seconds: float | None
    sessions_created: int
    completed_hours: float
    total_hours: float
    message: str | None
    finished: bool
    current_label: str | None
    current_week_label: str | None
    current_week_sessions: List[dict[str, object]]


class ScheduleProgressTracker(ScheduleProgress):
    """Thread-safe tracker collecting scheduling progress."""

    SUCCESS_STATES = {"success", "error"}

    def __init__(self, label: str) -> None:
        self.job_id = uuid.uuid4().hex
        self.label = label
        self._total_hours = 0.0
        self._completed_hours = 0.0
        self._sessions_created = 0
        self._state = "pending"
        self._message: str | None = None
        self._lock = threading.Lock()
        self._started_at: float | None = None
        self._finished_at: float | None = None
        self._current_label: str | None = None
        self._current_week_label: str | None = None
        self._current_week_sessions: List[dict[str, object]] = []

    # Public helpers -------------------------------------------------
    def initialise(self, total_hours: float) -> None:
        with self._lock:
            self._total_hours = max(float(total_hours), 0.0)
            self._completed_hours = min(self._completed_hours, self._total_hours)
            self._sessions_created = max(self._sessions_created, 0)
            self._state = "running"
            now = time.monotonic()
            if self._started_at is None:
                self._started_at = now
            self._finished_at = None

    def record(self, hours: float, sessions: int = 0) -> None:
        if hours <= 0 and sessions <= 0:
            return
        with self._lock:
            self._completed_hours = min(
                self._total_hours,
                max(self._completed_hours + max(float(hours), 0.0), 0.0),
            )
            if sessions > 0:
                self._sessions_created = max(self._sessions_created + sessions, 0)
            if self._state == "pending":
                self._state = "running"
            if self._started_at is None:
                self._started_at = time.monotonic()

    def complete(self, message: str | None = None) -> None:
        with self._lock:
            self._state = "success"
            self._completed_hours = max(self._total_hours, self._completed_hours)
            self._message = message.strip() if message else self._message
            if self._started_at is None:
                self._started_at = time.monotonic()
            self._finished_at = time.monotonic()
            self._current_label = None

    def fail(self, message: str) -> None:
        with self._lock:
            self._state = "error"
            self._message = message.strip() if message else None
            if self._started_at is None:
                self._started_at = time.monotonic()
            self._finished_at = time.monotonic()
            self._current_label = None

    def update_week_overview(
        self, week_label: str | None, entries: List[dict[str, object]]
    ) -> None:
        with self._lock:
            self._current_week_label = week_label
            self._current_week_sessions = list(entries)

    # Snapshot -------------------------------------------------------
    def snapshot(self) -> ProgressSnapshot:
        with self._lock:
            percent = self._percent_locked()
            eta = self._eta_locked()
            finished = self._state in self.SUCCESS_STATES
            message = self._message
            return ProgressSnapshot(
                job_id=self.job_id,
                label=self.label,
                state=self._state,
                percent=percent,
                eta_seconds=eta,
                sessions_created=self._sessions_created,
                completed_hours=self._completed_hours,
                total_hours=self._total_hours,
                message=message,
                finished=finished,
                current_label=self._current_label,
                current_week_label=self._current_week_label,
                current_week_sessions=list(self._current_week_sessions),
            )

    def is_finished(self) -> bool:
        with self._lock:
            return self._state in self.SUCCESS_STATES

    def age(self) -> float:
        reference = self._finished_at or self._started_at or time.monotonic()
        return time.monotonic() - reference

    # Internal helpers -----------------------------------------------
    def _percent_locked(self) -> int:
        if self._total_hours <= 0:
            return 100 if self._state == "success" else 0
        ratio = self._completed_hours / self._total_hours
        if self._state == "success":
            ratio = 1.0
        return max(0, min(int(round(ratio * 100)), 100))

    def _eta_locked(self) -> float | None:
        if (
            self._state != "running"
            or self._total_hours <= 0
            or self._completed_hours <= 0
        ):
            return None
        if self._completed_hours >= self._total_hours:
            return 0.0
        if self._started_at is None:
            return None
        elapsed = time.monotonic() - self._started_at
        ratio = self._completed_hours / self._total_hours
        if ratio <= 0:
            return None
        remaining_ratio = max(1.0 / ratio - 1.0, 0.0)
        return max(elapsed * remaining_ratio, 0.0)

    # Coordination helpers ------------------------------------------
    def set_current_label(self, label: str | None) -> None:
        with self._lock:
            if label is None:
                self._current_label = None
            else:
                stripped = label.strip()
                self._current_label = stripped or None
            if self._state == "pending":
                self._state = "running"
                if self._started_at is None:
                    self._started_at = time.monotonic()

    def create_slice(self, label: str | None = None) -> "ScheduleProgressSlice":
        return ScheduleProgressSlice(self, label=label)


class ScheduleProgressSlice(ScheduleProgress):
    """Adapter used to feed a shared tracker for nested jobs."""

    def __init__(self, tracker: ScheduleProgressTracker, *, label: str | None = None) -> None:
        self._tracker = tracker
        self._label = label

    def initialise(self, total_hours: float) -> None:
        self._tracker.set_current_label(self._label)

    def record(self, hours: float, sessions: int = 0) -> None:
        self._tracker.record(hours, sessions=sessions)

    def complete(self, message: str | None = None) -> None:
        self._tracker.set_current_label(None)

    def update_week_overview(
        self, week_label: str | None, entries: List[dict[str, object]]
    ) -> None:
        self._tracker.update_week_overview(week_label, entries)


class ProgressRegistry:
    """In-memory registry storing active scheduling trackers."""

    def __init__(self) -> None:
        self._trackers: Dict[str, ScheduleProgressTracker] = {}
        self._lock = threading.Lock()

    def register(self, tracker: ScheduleProgressTracker) -> None:
        with self._lock:
            self._trackers[tracker.job_id] = tracker

    def create(self, label: str) -> ScheduleProgressTracker:
        tracker = ScheduleProgressTracker(label)
        self.register(tracker)
        return tracker

    def get(self, job_id: str) -> ScheduleProgressTracker | None:
        with self._lock:
            return self._trackers.get(job_id)

    def remove(self, job_id: str) -> None:
        with self._lock:
            self._trackers.pop(job_id, None)

    def purge(self, max_age_seconds: float = 600.0) -> None:
        with self._lock:
            stale_ids = [
                job_id
                for job_id, tracker in self._trackers.items()
                if tracker.is_finished() and tracker.age() > max_age_seconds
            ]
            for job_id in stale_ids:
                self._trackers.pop(job_id, None)


progress_registry = ProgressRegistry()

