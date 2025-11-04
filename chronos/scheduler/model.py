"""Internal data structures used by the Chronos scheduler."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, time, timedelta
from typing import Dict, Iterable, List, Sequence


@dataclass(frozen=True)
class TimeSlot:
    """Represents a discrete slot in the time grid."""

    slot_id: str
    day: date
    start: time
    end: time

    @property
    def duration(self) -> timedelta:
        return datetime_combine(self.day, self.end) - datetime_combine(self.day, self.start)


@dataclass
class Teacher:
    teacher_id: str
    name: str
    can_teach: Dict[str, Sequence[str]]
    availability: set[str]
    hard_unavailability: set[str]
    max_per_day: int | None = None
    max_per_week: int | None = None
    min_per_day: int | None = None
    preferred_slots: set[str] = field(default_factory=set)
    disliked_slots: set[str] = field(default_factory=set)


@dataclass
class Group:
    group_id: str
    name: str
    size: int
    incompatible_with: set[str] = field(default_factory=set)


@dataclass
class Room:
    room_id: str
    name: str
    capacity: int
    equipment: set[str] = field(default_factory=set)


@dataclass
class Course:
    course_id: str
    module_id: str
    type: str
    duration_minutes: int
    total_units: int
    groups: Sequence[str]
    allowed_time_slots: set[str] | None = None
    precedence: Sequence[str] = field(default_factory=list)
    preferred_slots: set[str] = field(default_factory=set)
    forbidden_slots: set[str] = field(default_factory=set)
    required_equipment: set[str] = field(default_factory=set)


@dataclass
class GlobalRules:
    forbidden_slots: set[str] = field(default_factory=set)
    lunch_start: time | None = None
    lunch_end: time | None = None
    lunch_break_minutes: int = 60
    daily_amplitude_minutes: int | None = None


@dataclass
class Session:
    session_id: str
    course_id: str
    module_id: str
    type: str
    groups: Sequence[str]
    duration_minutes: int


@dataclass
class ScheduleResult:
    sessions: List[dict]
    metrics: Dict[str, object]


def datetime_combine(day: date, value: time) -> datetime:
    from datetime import datetime

    return datetime.combine(day, value)


def minutes_between(start: time, end: time) -> int:
    delta = datetime_combine(date.today(), end) - datetime_combine(date.today(), start)
    return int(delta.total_seconds() // 60)


def slots_covering_interval(slots: Iterable[TimeSlot], start: time, end: time) -> List[TimeSlot]:
    return [slot for slot in slots if not (slot.end <= start or slot.start >= end)]
