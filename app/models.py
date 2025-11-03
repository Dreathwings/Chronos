from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from math import ceil
from itertools import combinations
from typing import Iterable, List, Optional, Set

from sqlalchemy import (
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import db
from .utils import parse_unavailability_ranges


course_software = Table(
    "course_software",
    db.Model.metadata,
    Column("course_id", ForeignKey("course.id"), primary_key=True),
    Column("software_id", ForeignKey("software.id"), primary_key=True),
)

course_equipment = Table(
    "course_equipment",
    db.Model.metadata,
    Column("course_id", ForeignKey("course.id"), primary_key=True),
    Column("equipment_id", ForeignKey("equipment.id"), primary_key=True),
)

room_equipment = Table(
    "room_equipment",
    db.Model.metadata,
    Column("room_id", ForeignKey("room.id"), primary_key=True),
    Column("equipment_id", ForeignKey("equipment.id"), primary_key=True),
)

room_software = Table(
    "room_software",
    db.Model.metadata,
    Column("room_id", ForeignKey("room.id"), primary_key=True),
    Column("software_id", ForeignKey("software.id"), primary_key=True),
)

course_teacher = Table(
    "course_teacher",
    db.Model.metadata,
    Column("course_id", ForeignKey("course.id"), primary_key=True),
    Column("teacher_id", ForeignKey("teacher.id"), primary_key=True),
)


course_name_preferred_room = Table(
    "course_name_preferred_room",
    db.Model.metadata,
    Column("course_name_id", ForeignKey("course_name.id"), primary_key=True),
    Column("room_id", ForeignKey("room.id"), primary_key=True),
)


session_attendance = Table(
    "session_attendance",
    db.Model.metadata,
    Column("session_id", ForeignKey("session.id"), primary_key=True),
    Column("class_group_id", ForeignKey("class_group.id"), primary_key=True),
)


def default_start_time() -> time:
    return time(8, 0)


def default_end_time() -> time:
    return time(18, 0)


class TimeStampedModel:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ClosingPeriod(db.Model, TimeStampedModel):
    id: Mapped[int] = mapped_column(primary_key=True)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    label: Mapped[Optional[str]] = mapped_column(String(255))

    __table_args__ = (
        CheckConstraint("end_date >= start_date", name="chk_closing_period_range"),
    )

    @classmethod
    def ordered_periods(cls) -> List["ClosingPeriod"]:
        return cls.query.order_by(cls.start_date, cls.end_date, cls.id).all()

    @classmethod
    def is_day_closed(cls, day: date) -> bool:
        return (
            cls.query.filter(cls.start_date <= day, cls.end_date >= day).first()
            is not None
        )

    @classmethod
    def overlaps(cls, start: date, end: date) -> bool:
        if start > end:
            start, end = end, start
        return (
            cls.query.filter(cls.start_date <= end, cls.end_date >= start).first()
            is not None
        )

    def as_range(self) -> tuple[date, date]:
        return (self.start_date, self.end_date)

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"ClosingPeriod<{self.start_date}→{self.end_date}>"


class Teacher(db.Model, TimeStampedModel):
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    email: Mapped[Optional[str]] = mapped_column(String(255))
    phone: Mapped[Optional[str]] = mapped_column(String(50))
    unavailable_dates: Mapped[Optional[str]] = mapped_column(Text)
    notes: Mapped[Optional[str]] = mapped_column(Text)

    sessions: Mapped[List["Session"]] = relationship(
        back_populates="teacher", cascade="all, delete-orphan"
    )
    courses: Mapped[List["Course"]] = relationship(
        secondary=course_teacher, back_populates="teachers"
    )
    availabilities: Mapped[List["TeacherAvailability"]] = relationship(
        back_populates="teacher",
        cascade="all, delete-orphan",
        order_by="TeacherAvailability.weekday",
    )

    def is_available_on(self, day: datetime | date) -> bool:
        target_date = day.date() if isinstance(day, datetime) else day
        if target_date.weekday() >= 5:
            return False
        for start, end in parse_unavailability_ranges(self.unavailable_dates):
            if start <= target_date <= end:
                return False
        return any(a.weekday == target_date.weekday() for a in self.availabilities)

    def is_available_during(self, start: datetime, end: datetime) -> bool:
        if not self.is_available_on(start):
            return False
        day_slots = sorted(
            (a for a in self.availabilities if a.weekday == start.weekday()),
            key=lambda a: a.start_time,
        )
        if not day_slots:
            return False
        coverage = start.time()
        target_end = end.time()
        for slot in day_slots:
            if slot.end_time <= coverage:
                continue
            if slot.start_time > coverage:
                return False
            if slot.end_time > coverage:
                coverage = slot.end_time
            if coverage >= target_end:
                return True
        return False

    def overlapping_available_hours(self, other: "Teacher") -> float:
        """Return the amount of overlapping availability with ``other`` in hours."""

        if other is self:
            return 0.0
        total = 0.0
        for weekday in range(7):
            my_slots = [a for a in self.availabilities if a.weekday == weekday]
            other_slots = [a for a in other.availabilities if a.weekday == weekday]
            if not my_slots or not other_slots:
                continue
            for mine in my_slots:
                for theirs in other_slots:
                    overlap = _availability_overlap_hours(mine, theirs)
                    if overlap > 0:
                        total += overlap
        return total

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"Teacher<{self.id} {self.name}>"


class Room(db.Model, TimeStampedModel):
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, default=20)
    computers: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[Optional[str]] = mapped_column(Text)

    equipments: Mapped[List["Equipment"]] = relationship(secondary=room_equipment, back_populates="rooms")
    softwares: Mapped[List["Software"]] = relationship(secondary=room_software, back_populates="rooms")
    sessions: Mapped[List["Session"]] = relationship(back_populates="room", cascade="all, delete-orphan")
    preferred_for_course_names: Mapped[List["CourseName"]] = relationship(
        "CourseName",
        secondary=course_name_preferred_room,
        back_populates="preferred_rooms",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"Room<{self.id} {self.name}>"


COURSE_TYPE_CHOICES = ("CM", "TD", "TP", "SAE", "Eval")
COURSE_TYPE_PLACEMENT_ORDER = ("CM", "SAE", "TD", "TP", "Eval")
COURSE_TYPE_LABELS = {
    "CM": "CM",
    "TD": "TD",
    "TP": "TP",
    "SAE": "SAE",
    "Eval":"Eval"
}
SEMESTER_CHOICES = ("S1", "S2", "S3", "S4", "S5", "S6")
SEMESTER_PLANNING_WINDOWS: dict[str, tuple[date, date]] = {
    "S1": (date(2025, 9, 1), date(2026, 1, 11)),
    "S3": (date(2025, 9, 1), date(2026, 1, 11)),
    "S5": (date(2025, 9, 1), date(2026, 1, 11)),
    "S2": (date(2026, 1, 12), date(2026, 7, 4)),
    "S4": (date(2026, 1, 12), date(2026, 7, 4)),
    "S6": (date(2026, 1, 12), date(2026, 7, 4)),
}


def semester_date_window(semester: str | None) -> tuple[date, date] | None:
    if not semester:
        return None
    return SEMESTER_PLANNING_WINDOWS.get(semester.strip().upper())


class Course(db.Model, TimeStampedModel):
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    session_length_hours: Mapped[int] = mapped_column(Integer, default=2)
    sessions_required: Mapped[int] = mapped_column(Integer, default=1)
    priority: Mapped[int] = mapped_column(Integer, default=1)
    course_type: Mapped[str] = mapped_column(String(3), default="CM")
    semester: Mapped[str] = mapped_column(String(2), default="S1")
    sessions_per_week: Mapped[int] = mapped_column(Integer, default=1)
    color: Mapped[Optional[str]] = mapped_column(String(7))
    course_name_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("course_name.id"), nullable=True
    )

    requires_computers: Mapped[bool] = mapped_column(db.Boolean, default=False)
    computers_required: Mapped[int] = mapped_column(Integer, default=0)

    configured_name: Mapped[Optional["CourseName"]] = relationship(
        "CourseName", back_populates="courses"
    )
    teachers: Mapped[List[Teacher]] = relationship(secondary=course_teacher, back_populates="courses")
    softwares: Mapped[List["Software"]] = relationship(secondary=course_software, back_populates="courses")
    equipments: Mapped[List["Equipment"]] = relationship(secondary=course_equipment, back_populates="courses")
    teacher_allocations: Mapped[List["CourseTeacherAllocation"]] = relationship(
        "CourseTeacherAllocation",
        back_populates="course",
        cascade="all, delete-orphan",
    )
    class_links: Mapped[List["CourseClassLink"]] = relationship(
        "CourseClassLink",
        back_populates="course",
        cascade="all, delete-orphan",
    )
    classes = association_proxy(
        "class_links",
        "class_group",
        creator=lambda class_group: CourseClassLink(class_group=class_group),
    )
    sessions: Mapped[List["Session"]] = relationship(back_populates="course", cascade="all, delete-orphan")

    generation_logs: Mapped[List["CourseScheduleLog"]] = relationship(
        "CourseScheduleLog",
        back_populates="course",
        cascade="all, delete-orphan",
        order_by="CourseScheduleLog.created_at.desc()",
    )
    allowed_weeks: Mapped[List["CourseAllowedWeek"]] = relationship(
        "CourseAllowedWeek",
        back_populates="course",
        cascade="all, delete-orphan",
        order_by="CourseAllowedWeek.week_start",
    )

    __table_args__ = (
        CheckConstraint("session_length_hours > 0", name="chk_session_length_positive"),
        CheckConstraint("sessions_required > 0", name="chk_session_required_positive"),
        CheckConstraint("sessions_per_week >= 0", name="chk_sessions_per_week_non_negative"),
        CheckConstraint("computers_required >= 0", name="chk_course_computers_non_negative"),
        CheckConstraint(
            "course_type IN ('CM','TD','TP','SAE','Eval')",
            name="chk_course_type_valid",
        ),
        CheckConstraint(
            "semester IN ('S1','S2','S3','S4','S5','S6')",
            name="chk_course_semester_valid",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"Course<{self.id} {self.name}>"

    @staticmethod
    def compose_name(course_type: str, base_label: str, semester: str) -> str:
        parts: list[str] = []
        course_type = (course_type or "").strip().upper()
        base_label = (base_label or "").strip()
        semester = (semester or "").strip().upper()
        if course_type:
            parts.append(course_type)
        if base_label:
            parts.append(base_label)
        if semester:
            parts.append(semester)
        return " - ".join(parts)

    @property
    def base_display_name(self) -> str:
        name = self.name or ""
        prefix = f"{self.course_type} - " if self.course_type else ""
        suffix = f" - {self.semester}" if self.semester else ""
        if prefix and name.startswith(prefix):
            name = name[len(prefix) :]
        if suffix and name.endswith(suffix):
            name = name[: len(name) - len(suffix)]
        return name.strip()

    @property
    def is_tp(self) -> bool:
        return self.course_type == "TP"

    @property
    def is_cm(self) -> bool:
        return self.course_type == "CM"

    @property
    def is_sae(self) -> bool:
        return self.course_type == "SAE"

    @property
    def semester_window(self) -> tuple[date, date] | None:
        return semester_date_window(self.semester)

    @property
    def semester_start(self) -> date | None:
        window = self.semester_window
        if window is None:
            return None
        return window[0]

    @property
    def semester_end(self) -> date | None:
        window = self.semester_window
        if window is None:
            return None
        return window[1]

    def class_link_for(self, class_group: "ClassGroup" | int) -> "CourseClassLink" | None:
        class_id = class_group if isinstance(class_group, int) else class_group.id
        for link in self.class_links:
            if link.class_group_id == class_id:
                return link
        return None

    def group_count_for(self, class_group: "ClassGroup" | int) -> int:
        link = self.class_link_for(class_group)
        return link.group_count if link else 1

    def group_labels_for(self, class_group: "ClassGroup" | int) -> list[str | None]:
        link = self.class_link_for(class_group)
        if link is None:
            return [None]
        return link.group_labels()

    @property
    def preferred_rooms(self) -> list["Room"]:
        if self.configured_name and self.configured_name.preferred_rooms:
            return list(self.configured_name.preferred_rooms)
        return []

    @property
    def allowed_week_ranges(self) -> list[tuple[date, date]]:
        return [entry.week_span for entry in self.allowed_weeks]

    @property
    def allowed_week_payload(self) -> list[tuple[date, date, int]]:
        fallback = max(int(self.sessions_per_week or 0), 0)
        payload: list[tuple[date, date, int]] = []
        for entry in self.allowed_weeks:
            payload.append(
                (
                    entry.week_start,
                    entry.week_end,
                    entry.effective_sessions(fallback),
                )
            )
        return payload

    def subgroup_name_for(
        self, class_group: "ClassGroup" | int, subgroup_label: str | None
    ) -> str | None:
        link = self.class_link_for(class_group)
        if link is None:
            return None
        return link.subgroup_name_for(subgroup_label)

    def capacity_needed_for(self, class_group: "ClassGroup" | int) -> int:
        link = self.class_link_for(class_group)
        if isinstance(class_group, int):
            target = next((cls for cls in self.classes if cls.id == class_group), None)
        else:
            target = class_group
        if target is None:
            return 1
        baseline = max(target.size, 1)
        if link and link.group_count > 1:
            return max(1, ceil(baseline / link.group_count))
        return max(1, baseline)

    def required_computer_posts(self) -> int:
        if not self.requires_computers:
            return 0
        value = self.computers_required or 0
        try:
            numeric = int(value)
        except (TypeError, ValueError):
            numeric = 0
        return max(numeric, 1)

    @property
    def scheduled_hours(self) -> int:
        return sum(session.duration_hours for session in self.sessions)

    @property
    def total_required_hours(self) -> int:
        group_total = sum(link.group_count for link in self.class_links)
        if self.is_cm:
            multiplier = 1
        else:
            multiplier = group_total or 1
        per_week_goal = max(int(self.sessions_per_week or 0), 0)
        if self.allowed_weeks:
            occurrences = sum(
                entry.effective_sessions(per_week_goal)
                for entry in self.allowed_weeks
            )
            if occurrences <= 0:
                occurrences = max(int(self.sessions_required or 0), 1)
        else:
            occurrences = max(
                int(self.sessions_required or 0),
                per_week_goal,
                1,
            )
        return occurrences * self.session_length_hours * multiplier

    @property
    def latest_generation_log(self) -> "CourseScheduleLog | None":
        return self.generation_logs[0] if self.generation_logs else None

    @property
    def teacher_allocation_map(self) -> dict[int, int]:
        mapping: dict[int, int] = {}
        for allocation in self.teacher_allocations:
            if allocation.teacher_id is None:
                continue
            mapping[allocation.teacher_id] = max(allocation.target_hours or 0, 0)
        return mapping


class Session(db.Model, TimeStampedModel):
    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("course.id"), nullable=False)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("teacher.id"), nullable=False)
    room_id: Mapped[int] = mapped_column(ForeignKey("room.id"), nullable=False)
    class_group_id: Mapped[int] = mapped_column(ForeignKey("class_group.id"), nullable=False)
    subgroup_label: Mapped[Optional[str]] = mapped_column(String(1))
    start_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    course: Mapped[Course] = relationship(back_populates="sessions")
    teacher: Mapped[Teacher] = relationship(back_populates="sessions")
    room: Mapped[Room] = relationship(back_populates="sessions")
    class_group: Mapped["ClassGroup"] = relationship(back_populates="sessions")
    attendees: Mapped[List["ClassGroup"]] = relationship(
        "ClassGroup",
        secondary=session_attendance,
        back_populates="attending_sessions",
        order_by="ClassGroup.name",
    )

    __table_args__ = (
        CheckConstraint("end_time > start_time", name="chk_session_time_order"),
        UniqueConstraint("room_id", "start_time", name="uq_room_start_time"),
        UniqueConstraint(
            "class_group_id",
            "subgroup_label",
            "start_time",
            name="uq_class_start_time",
        ),
    )

    def attendee_ids(self) -> Set[int]:
        if self.attendees:
            return {class_group.id for class_group in self.attendees}
        if self.class_group_id:
            return {self.class_group_id}
        return set()

    def attendee_names(self) -> List[str]:
        attendees = self.attendees or ([self.class_group] if self.class_group else [])
        return [class_group.name for class_group in sorted(attendees, key=lambda cg: cg.name.lower())]

    def title_with_room(self, room_label: str | None = None) -> str:
        room_name = room_label or self.room.name
        class_label = " + ".join(self.attendee_names()) or self.class_group.name
        subgroup_name = self.subgroup_display_name()
        if subgroup_name:
            group_suffix = f" — {subgroup_name}"
        elif self.subgroup_label:
            group_suffix = f" — groupe {self.subgroup_label}"
        else:
            group_suffix = ""
        return f"{self.course.name} — {class_label}{group_suffix} ({room_name})"

    def subgroup_display_name(self) -> Optional[str]:
        if not self.subgroup_label:
            return None
        course = getattr(self, "course", None)
        if course is None:
            return None
        return course.subgroup_name_for(self.class_group_id, self.subgroup_label)

    def as_event(self) -> dict[str, object]:
        title = self.title_with_room()
        course_softwares = sorted(software.name for software in self.course.softwares)
        room_softwares = sorted(software.name for software in self.room.softwares)
        room_software_ids = {software.id for software in self.room.softwares}
        missing_softwares = sorted(
            software.name
            for software in self.course.softwares
            if software.id not in room_software_ids
        )
        class_names = self.attendee_names()

        teacher_entries: list[dict[str, object]] = []
        seen_teacher_ids: set[int] = set()
        primary_teacher = self.teacher
        if primary_teacher is not None:
            seen_teacher_ids.add(primary_teacher.id)
            teacher_entries.append(
                {
                    "id": primary_teacher.id,
                    "name": primary_teacher.name,
                    "email": primary_teacher.email,
                    "phone": primary_teacher.phone,
                }
            )

        related_class_ids: set[int] = set()
        related_class_labels: dict[int, str | None] = {}
        if self.class_group_id:
            related_class_ids.add(self.class_group_id)
            related_class_labels[self.class_group_id] = self.subgroup_label
        for attendee in self.attendees or []:
            if attendee.id:
                related_class_ids.add(attendee.id)
                related_class_labels.setdefault(
                    attendee.id,
                    self.subgroup_label if attendee.id == self.class_group_id else None,
                )

        if self.course is not None and related_class_ids:
            for link in self.course.class_links:
                if link.class_group_id not in related_class_ids:
                    continue
                if self.course.is_sae:
                    candidate_teachers = link.assigned_teachers()
                else:
                    subgroup_label = related_class_labels.get(link.class_group_id)
                    preferred_teacher = link.teacher_for_label(subgroup_label)
                    if preferred_teacher is not None:
                        candidate_teachers = [preferred_teacher]
                    else:
                        candidate_teachers = link.assigned_teachers()
                for teacher in candidate_teachers:
                    if teacher is None or teacher.id in seen_teacher_ids:
                        continue
                    seen_teacher_ids.add(teacher.id)
                    teacher_entries.append(
                        {
                            "id": teacher.id,
                            "name": teacher.name,
                            "email": teacher.email,
                            "phone": teacher.phone,
                        }
                    )

        primary_entry: dict[str, object] | None = teacher_entries[0] if teacher_entries else None
        primary_name = (
            primary_entry.get("name") if isinstance(primary_entry, dict) else None
        )
        primary_email = (
            primary_entry.get("email") if isinstance(primary_entry, dict) else None
        )
        primary_phone = (
            primary_entry.get("phone") if isinstance(primary_entry, dict) else None
        )

        return {
            "id": str(self.id),
            "title": title,
            "start": self.start_time.isoformat(),
            "end": self.end_time.isoformat(),
            "extendedProps": {
                "teacher": primary_name,
                "teacher_email": primary_email,
                "teacher_phone": primary_phone,
                "teachers": teacher_entries,
                "course": self.course.name,
                "course_type": self.course.course_type,
                "course_type_label": COURSE_TYPE_LABELS.get(
                    self.course.course_type, self.course.course_type
                ),
                "course_description": self.course.description,
                "requires_computers": self.course.requires_computers,
                "computers_required": self.course.required_computer_posts(),
                "room_computers": self.room.computers,
                "course_softwares": course_softwares,
                "room_softwares": room_softwares,
                "missing_softwares": missing_softwares,
                "room": self.room.name,
                "rooms": [self.room.name],
                "class_group": ", ".join(class_names),
                "class_groups": class_names,
                "subgroup": self.subgroup_label,
                "subgroup_name": self.subgroup_display_name(),
                "segments": [
                    {
                        "id": str(self.id),
                        "start": self.start_time.isoformat(),
                        "end": self.end_time.isoformat(),
                        "room": self.room.name,
                    }
                ],
                "segment_ids": [str(self.id)],
                "is_grouped": False,
            },
        }

    @property
    def duration_hours(self) -> int:
        delta = self.end_time - self.start_time
        return max(int(delta.total_seconds() // 3600), 0)


class CourseScheduleLog(db.Model, TimeStampedModel):
    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("course.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), default="success")
    summary: Mapped[Optional[str]] = mapped_column(Text)
    messages: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    window_start: Mapped[Optional[date]] = mapped_column(Date)
    window_end: Mapped[Optional[date]] = mapped_column(Date)

    course: Mapped[Course] = relationship("Course", back_populates="generation_logs")

    __table_args__ = (
        CheckConstraint(
            "status IN ('success','warning','error')",
            name="chk_course_schedule_log_status",
        ),
    )

    STATUS_LABELS = {
        "success": "Succès",
        "warning": "Avertissement",
        "error": "Erreur",
    }

    LEVEL_LABELS = {
        "info": "Info",
        "warning": "Avertissement",
        "error": "Erreur",
    }

    def parsed_messages(self) -> list[dict[str, object]]:
        try:
            payload = json.loads(self.messages or "[]")
        except (TypeError, ValueError):
            return []
        if not isinstance(payload, list):
            return []
        normalised: list[dict[str, object]] = []
        for entry in payload:
            if not isinstance(entry, dict):
                continue
            level = str(entry.get("level", "info")).lower()
            message = str(entry.get("message", "")).strip()
            if not message:
                continue
            normalised_entry: dict[str, object] = {"level": level, "message": message}
            suggestions = entry.get("suggestions")
            if isinstance(suggestions, list):
                unique: list[str] = []
                for suggestion in suggestions:
                    cleaned = str(suggestion).strip()
                    if cleaned and cleaned not in unique:
                        unique.append(cleaned)
                if unique:
                    normalised_entry["suggestions"] = unique
            normalised.append(normalised_entry)
        return normalised

    @property
    def status_label(self) -> str:
        return self.STATUS_LABELS.get(self.status, self.status)

    def level_label(self, level: str) -> str:
        return self.LEVEL_LABELS.get(level, level.title())


class CourseAllowedWeek(db.Model, TimeStampedModel):
    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("course.id"), nullable=False)
    week_start: Mapped[date] = mapped_column(Date, nullable=False)
    sessions_target: Mapped[Optional[int]] = mapped_column(Integer)

    course: Mapped["Course"] = relationship("Course", back_populates="allowed_weeks")

    __table_args__ = (
        UniqueConstraint(
            "course_id",
            "week_start",
            name="uq_course_allowed_week_unique",
        ),
        CheckConstraint(
            "sessions_target IS NULL OR sessions_target >= 0",
            name="chk_course_allowed_week_sessions_non_negative",
        ),
    )

    @property
    def week_end(self) -> date:
        return self.week_start + timedelta(days=6)

    @property
    def week_span(self) -> tuple[date, date]:
        return self.week_start, self.week_end

    def effective_sessions(self, default: int) -> int:
        value = self.sessions_target
        if value is None:
            return max(int(default or 0), 0)
        try:
            return max(int(value), 0)
        except (TypeError, ValueError):
            return max(int(default or 0), 0)


class Equipment(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)

    rooms: Mapped[List[Room]] = relationship(secondary=room_equipment, back_populates="equipments")
    courses: Mapped[List[Course]] = relationship(secondary=course_equipment, back_populates="equipments")

    def __repr__(self) -> str:  # pragma: no cover
        return f"Equipment<{self.name}>"


class Software(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)

    rooms: Mapped[List[Room]] = relationship(secondary=room_software, back_populates="softwares")
    courses: Mapped[List[Course]] = relationship(secondary=course_software, back_populates="softwares")

    def __repr__(self) -> str:  # pragma: no cover
        return f"Software<{self.name}>"


class CourseName(db.Model, TimeStampedModel):
    __tablename__ = "course_name"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)

    courses: Mapped[List[Course]] = relationship(
        "Course", back_populates="configured_name"
    )

    preferred_rooms: Mapped[List[Room]] = relationship(
        "Room",
        secondary=course_name_preferred_room,
        back_populates="preferred_for_course_names",
    )

    subgroup_links_a: Mapped[List["CourseClassLink"]] = relationship(
        "CourseClassLink",
        foreign_keys="CourseClassLink.subgroup_a_course_name_id",
        back_populates="subgroup_a_course_name",
    )
    subgroup_links_b: Mapped[List["CourseClassLink"]] = relationship(
        "CourseClassLink",
        foreign_keys="CourseClassLink.subgroup_b_course_name_id",
        back_populates="subgroup_b_course_name",
    )

    @property
    def usage_count(self) -> int:
        return len(self.subgroup_links_a) + len(self.subgroup_links_b)

    def __repr__(self) -> str:  # pragma: no cover
        return f"CourseName<{self.name}>"


class TeacherAvailability(db.Model, TimeStampedModel):
    id: Mapped[int] = mapped_column(primary_key=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("teacher.id"), nullable=False)
    weekday: Mapped[int] = mapped_column(Integer, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)

    teacher: Mapped[Teacher] = relationship(back_populates="availabilities")

    __table_args__ = (
        CheckConstraint("end_time > start_time", name="chk_availability_time_order"),
        CheckConstraint("weekday >= 0 AND weekday <= 6", name="chk_availability_weekday_range"),
    )

    def contains(self, start: time, end: time) -> bool:
        return self.start_time <= start and end <= self.end_time

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"TeacherAvailability<Teacher {self.teacher_id} day {self.weekday} "
            f"{self.start_time}-{self.end_time}>"
        )


def _availability_overlap_hours(
    first: TeacherAvailability, second: TeacherAvailability
) -> float:
    start = max(first.start_time, second.start_time)
    end = min(first.end_time, second.end_time)
    if end <= start:
        return 0.0
    delta = datetime.combine(date.min, end) - datetime.combine(date.min, start)
    return delta.total_seconds() / 3600


def best_teacher_duos(
    teachers: Iterable[Teacher], *, limit: int | None = 5
) -> list[tuple[Teacher, Teacher, float]]:
    """Return the best teacher pairs ranked by shared availability hours.

    The returned list is ordered from the most overlapping availability to the
    least. Each entry is a tuple ``(teacher_a, teacher_b, overlap_hours)``.
    ``limit`` controls the maximum number of pairs returned; pass ``None`` to
    retrieve every combination.
    """

    unique: list[Teacher] = []
    seen: set[int] = set()
    for teacher in teachers:
        if teacher is None:
            continue
        teacher_id = teacher.id or id(teacher)
        if teacher_id in seen:
            continue
        seen.add(teacher_id)
        unique.append(teacher)

    pairs: list[tuple[Teacher, Teacher, float]] = []
    for first, second in combinations(unique, 2):
        overlap = first.overlapping_available_hours(second)
        pairs.append((first, second, overlap))

    pairs.sort(
        key=lambda item: (
            -item[2],
            (item[0].name or "").lower(),
            (item[1].name or "").lower(),
        )
    )

    if limit is not None and limit >= 0:
        return pairs[:limit]
    return pairs


def recommend_teacher_duos_for_classes(
    class_links: Iterable["CourseClassLink"],
    teachers: Iterable[Teacher],
) -> dict[int, tuple[Teacher, Teacher, float]]:
    """Suggest one teacher duo per class without reusing instructors.

    The returned mapping uses the ``class_group_id`` of each ``CourseClassLink``
    as key and associates it with the selected ``(teacher_a, teacher_b,
    overlap_hours)`` tuple. If a class cannot be assigned a duo without
    duplicating teachers, it will be omitted from the mapping. When several
    pairings are possible, the combination that maximises the mean shared
    availability across the recommended duos is selected, breaking ties on the
    total shared time and then alphabetically by teacher names.
    """

    unique_teachers: list[Teacher] = []
    unique_ids: list[int] = []
    seen: set[int] = set()
    for teacher in teachers:
        if teacher is None:
            continue
        identifier = teacher.id or id(teacher)
        if identifier in seen:
            continue
        seen.add(identifier)
        unique_teachers.append(teacher)
        unique_ids.append(identifier)

    teacher_count = len(unique_teachers)
    if teacher_count < 2:
        return {}

    resolved_links: list[tuple[int, "CourseClassLink"]] = []
    for link in class_links:
        class_group_id = link.class_group_id
        if class_group_id is None and link.class_group is not None:
            class_group_id = link.class_group.id
        if class_group_id is None:
            continue
        resolved_links.append((class_group_id, link))

    if not resolved_links:
        return {}

    resolved_links.sort(key=lambda item: item[0])

    pairs_needed = min(len(resolved_links), teacher_count // 2)
    if pairs_needed == 0:
        return {}

    overlaps: list[list[float]] = [
        [0.0 for _ in range(teacher_count)] for _ in range(teacher_count)
    ]
    for first_index in range(teacher_count):
        first_teacher = unique_teachers[first_index]
        for second_index in range(first_index + 1, teacher_count):
            second_teacher = unique_teachers[second_index]
            overlap = first_teacher.overlapping_available_hours(second_teacher)
            overlaps[first_index][second_index] = overlap
            overlaps[second_index][first_index] = overlap

    teacher_sort_key = [
        ((teacher.name or "").lower(), unique_ids[index])
        for index, teacher in enumerate(unique_teachers)
    ]

    def canonical_pairs(pairs: tuple[tuple[int, int], ...]) -> tuple[tuple[int, int], ...]:
        return tuple(
            sorted(
                pairs,
                key=lambda pair: (
                    teacher_sort_key[pair[0]],
                    teacher_sort_key[pair[1]],
                ),
            )
        )

    def signature(pairs: tuple[tuple[int, int], ...]) -> tuple[tuple[tuple[str, int], tuple[str, int]], ...]:
        return tuple(
            (
                teacher_sort_key[pair[0]],
                teacher_sort_key[pair[1]],
            )
            for pair in pairs
        )

    if hasattr(int, "bit_count"):
        def popcount(value: int) -> int:
            return value.bit_count()
    else:  # pragma: no cover - only executed on Python < 3.8
        def popcount(value: int) -> int:
            count = 0
            while value:
                value &= value - 1
                count += 1
            return count

    best_pairs: tuple[tuple[int, int], ...] = ()
    best_average = float("-inf")
    best_total = float("-inf")
    best_signature: tuple[tuple[tuple[str, int], tuple[str, int]], ...] | None = None

    def explore(mask: int, selected: tuple[tuple[int, int], ...], total: float) -> None:
        nonlocal best_pairs, best_average, best_total, best_signature

        selected_count = len(selected)
        remaining_pairs = pairs_needed - selected_count
        if remaining_pairs == 0:
            if not selected:
                return
            canonical = canonical_pairs(selected)
            mean_overlap = total / selected_count if selected_count else 0.0
            candidate_signature = signature(canonical)
            if (
                mean_overlap > best_average
                or (
                    mean_overlap == best_average
                    and (
                        total > best_total
                        or (
                            total == best_total
                            and (
                                best_signature is None
                                or candidate_signature < best_signature
                            )
                        )
                    )
                )
            ):
                best_pairs = canonical
                best_average = mean_overlap
                best_total = total
                best_signature = candidate_signature
            return

        if popcount(mask) < remaining_pairs * 2:
            return

        lowest_bit = mask & -mask
        first_index = lowest_bit.bit_length() - 1
        without_first = mask & ~lowest_bit

        explore(without_first, selected, total)

        other_mask = without_first
        while other_mask:
            lowest_other_bit = other_mask & -other_mask
            second_index = lowest_other_bit.bit_length() - 1
            other_mask &= ~lowest_other_bit

            pair = (
                min(first_index, second_index),
                max(first_index, second_index),
            )
            pair_score = overlaps[pair[0]][pair[1]]
            explore(
                without_first & ~lowest_other_bit,
                selected + (pair,),
                total + pair_score,
            )

    full_mask = (1 << teacher_count) - 1
    explore(full_mask, (), 0.0)

    selected_pairs = best_pairs

    if not selected_pairs:
        return {}

    selected_pairs_for_assignment = sorted(
        selected_pairs,
        key=lambda pair: (
            -overlaps[pair[0]][pair[1]],
            teacher_sort_key[pair[0]],
            teacher_sort_key[pair[1]],
        ),
    )

    selected_pairs_list: list[tuple[Teacher, Teacher, float]] = [
        (
            unique_teachers[first_index],
            unique_teachers[second_index],
            overlaps[first_index][second_index],
        )
        for first_index, second_index in selected_pairs_for_assignment
    ]

    assignments: dict[int, tuple[Teacher, Teacher, float]] = {}
    for (class_group_id, _), pair in zip(resolved_links, selected_pairs_list):
        assignments[class_group_id] = pair

    return assignments


class ClassGroup(db.Model, TimeStampedModel):
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150), unique=True, nullable=False)
    size: Mapped[int] = mapped_column(Integer, default=20)
    unavailable_dates: Mapped[Optional[str]] = mapped_column(Text)
    notes: Mapped[Optional[str]] = mapped_column(Text)

    course_links: Mapped[List["CourseClassLink"]] = relationship(
        "CourseClassLink",
        back_populates="class_group",
        cascade="all, delete-orphan",
    )
    courses = association_proxy(
        "course_links",
        "course",
        creator=lambda course: CourseClassLink(course=course),
    )
    sessions: Mapped[List[Session]] = relationship(
        back_populates="class_group", cascade="all, delete-orphan"
    )
    attending_sessions: Mapped[List[Session]] = relationship(
        "Session",
        secondary=session_attendance,
        back_populates="attendees",
    )
    students: Mapped[List["Student"]] = relationship(
        "Student",
        back_populates="class_group",
        cascade="all, delete-orphan",
        order_by="Student.full_name",
    )

    @staticmethod
    def _overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
        return max(a_start, b_start) < min(a_end, b_end)

    def _unavailable_set(self) -> set[str]:
        if not self.unavailable_dates:
            return set()
        tokens = self.unavailable_dates.replace("\n", ",").split(",")
        return {token.strip() for token in tokens if token.strip()}

    def is_available_on(self, day: datetime | date) -> bool:
        target_date = day.date() if isinstance(day, datetime) else day
        if target_date.weekday() >= 5:
            return False
        if ClosingPeriod.is_day_closed(target_date):
            return False
        if target_date.strftime("%Y-%m-%d") in self._unavailable_set():
            return False
        return True

    def is_available_during(
        self,
        start: datetime,
        end: datetime,
        *,
        ignore_session_id: Optional[int] = None,
        subgroup_label: Optional[str] = None,
    ) -> bool:
        if not self.is_available_on(start):
            return False
        target_label = (subgroup_label or "").strip().upper() or None
        seen: set[int | None] = set()
        for session in self.sessions + self.attending_sessions:
            if session.id in seen:
                continue
            if ignore_session_id and session.id == ignore_session_id:
                seen.add(session.id)
                continue
            if not self._overlaps(session.start_time, session.end_time, start, end):
                seen.add(session.id)
                continue
            session_label: str | None
            if session.class_group_id == self.id:
                session_label = (session.subgroup_label or "").strip().upper() or None
            else:
                attendees = session.attendees or []
                if any(att.id == self.id for att in attendees):
                    session_label = None
                else:
                    seen.add(session.id)
                    continue
            if target_label is not None:
                if session_label is None:
                    return False
                if session_label != target_label:
                    seen.add(session.id)
                    continue
            return False
            seen.add(session.id)
        return True

    @property
    def all_sessions(self) -> List[Session]:
        combined: list[Session] = []
        seen: set[int] = set()
        for session in self.sessions + self.attending_sessions:
            if session.id in seen:
                continue
            combined.append(session)
            seen.add(session.id)
        return sorted(
            combined,
            key=lambda session: (session.start_time, session.id or 0),
        )

    def __repr__(self) -> str:  # pragma: no cover
        return f"ClassGroup<{self.id} {self.name}>"


class Student(db.Model, TimeStampedModel):
    id: Mapped[int] = mapped_column(primary_key=True)
    class_group_id: Mapped[int] = mapped_column(
        ForeignKey("class_group.id"), nullable=False, index=True
    )
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[Optional[str]] = mapped_column(String(255))
    group_label: Mapped[Optional[str]] = mapped_column(String(50))
    phase: Mapped[Optional[str]] = mapped_column(String(50))
    pathway: Mapped[str] = mapped_column(
        String(20), default="initial", server_default="initial", nullable=False
    )
    alternance_details: Mapped[Optional[str]] = mapped_column(Text)
    ina_id: Mapped[Optional[str]] = mapped_column(String(50))
    ub_id: Mapped[Optional[str]] = mapped_column(String(50))
    notes: Mapped[Optional[str]] = mapped_column(Text)

    class_group: Mapped[ClassGroup] = relationship("ClassGroup", back_populates="students")

    PATHWAY_LABELS = {
        "initial": "Initial",
        "alternance": "Alternance",
    }

    __table_args__ = (
        UniqueConstraint(
            "class_group_id",
            "full_name",
            name="uq_student_class_unique_name",
        ),
    )

    @property
    def display_name(self) -> str:
        return self.full_name

    @property
    def pathway_label(self) -> str:
        return self.PATHWAY_LABELS.get(self.pathway, self.pathway or "")

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"Student<{self.id} {self.full_name}>"


class CourseClassLink(db.Model):
    __tablename__ = "course_class"

    course_id: Mapped[int] = mapped_column(ForeignKey("course.id"), primary_key=True)
    class_group_id: Mapped[int] = mapped_column(ForeignKey("class_group.id"), primary_key=True)
    group_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    teacher_a_id: Mapped[Optional[int]] = mapped_column(ForeignKey("teacher.id"))
    teacher_b_id: Mapped[Optional[int]] = mapped_column(ForeignKey("teacher.id"))
    subgroup_a_course_name_id: Mapped[Optional[int]] = mapped_column(ForeignKey("course_name.id"))
    subgroup_b_course_name_id: Mapped[Optional[int]] = mapped_column(ForeignKey("course_name.id"))

    course: Mapped[Course] = relationship(back_populates="class_links")
    class_group: Mapped[ClassGroup] = relationship(back_populates="course_links")
    teacher_a: Mapped[Optional[Teacher]] = relationship("Teacher", foreign_keys=[teacher_a_id])
    teacher_b: Mapped[Optional[Teacher]] = relationship("Teacher", foreign_keys=[teacher_b_id])
    subgroup_a_course_name: Mapped[Optional[CourseName]] = relationship(
        "CourseName",
        foreign_keys=[subgroup_a_course_name_id],
        back_populates="subgroup_links_a",
    )
    subgroup_b_course_name: Mapped[Optional[CourseName]] = relationship(
        "CourseName",
        foreign_keys=[subgroup_b_course_name_id],
        back_populates="subgroup_links_b",
    )

    __table_args__ = (
        CheckConstraint("group_count >= 1 AND group_count <= 2", name="chk_course_class_group_count"),
    )

    @property
    def is_half_group(self) -> bool:
        return self.group_count == 2

    def group_label(self) -> str:
        return "Demi-groupes" if self.is_half_group else "Classe entière"

    def group_labels(self) -> list[str | None]:
        if self.group_count == 2:
            return ["A", "B"]
        return [None]

    def subgroup_course_name_for(self, subgroup_label: str | None) -> CourseName | None:
        if not subgroup_label or self.group_count != 2:
            return None
        label = (subgroup_label or "").strip().upper()
        if label == "A":
            return self.subgroup_a_course_name
        if label == "B":
            return self.subgroup_b_course_name
        return None

    def subgroup_name_for(self, subgroup_label: str | None) -> str:
        if self.group_count != 2 or not subgroup_label:
            return self.course.name
        name = self.subgroup_course_name_for(subgroup_label)
        if name is not None:
            return name.name
        return f"Groupe {(subgroup_label or '').strip().upper()}"

    def labeled_subgroups(self) -> list[tuple[str | None, str]]:
        return [
            (label, self.subgroup_name_for(label))
            for label in self.group_labels()
        ]

    @property
    def has_named_subgroups(self) -> bool:
        if self.group_count != 2:
            return True
        return bool(self.subgroup_a_course_name and self.subgroup_b_course_name)

    def assigned_teachers(self) -> list[Teacher]:
        teachers: list[Teacher] = []
        for teacher in (self.teacher_a, self.teacher_b):
            if teacher is None:
                continue
            if teacher not in teachers:
                teachers.append(teacher)
        return teachers

    def preferred_teachers(self, subgroup_label: str | None = None) -> list[Teacher]:
        teachers = self.assigned_teachers()
        course = getattr(self, "course", None)
        course_type = getattr(course, "course_type", None)
        if course_type == "SAE":
            return teachers
        if self.group_count == 2:
            label = (subgroup_label or "").strip().upper()
            ordered: list[Teacher] = []
            if label == "A":
                if self.teacher_a:
                    ordered.append(self.teacher_a)
                if not ordered and self.teacher_b:
                    ordered.append(self.teacher_b)
            elif label == "B":
                if self.teacher_b:
                    ordered.append(self.teacher_b)
                if not ordered and self.teacher_a:
                    ordered.append(self.teacher_a)
            else:
                if self.teacher_a:
                    ordered.append(self.teacher_a)
                if self.teacher_b and self.teacher_b not in ordered:
                    ordered.append(self.teacher_b)
            if (
                label in {"A", "B"}
                and self.teacher_a
                and self.teacher_b
                and self.teacher_a.id != self.teacher_b.id
            ):
                return ordered[:1]
            return ordered
        if teachers:
            return teachers[:1]
        return []

    def teacher_for_label(self, subgroup_label: str | None) -> Optional[Teacher]:
        teachers = self.preferred_teachers(subgroup_label)
        return teachers[0] if teachers else None

    def teacher_labels(self) -> list[tuple[str, Optional[Teacher]]]:
        course = getattr(self, "course", None)
        course_type = getattr(course, "course_type", None)
        if course_type == "SAE":
            return [
                ("Enseignant 1", self.teacher_a),
                ("Enseignant 2", self.teacher_b),
            ]
        teacher = self.teacher_a or self.teacher_b
        if self.group_count == 2:
            return [
                (self.subgroup_name_for("A"), self.teacher_for_label("A")),
                (self.subgroup_name_for("B"), self.teacher_for_label("B")),
            ]
        return [("", teacher)]

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"CourseClassLink<Course {self.course_id} / Class {self.class_group_id} "
            f"groups={self.group_count}>"
        )


class CourseTeacherAllocation(db.Model):
    __tablename__ = "course_teacher_allocation"

    course_id: Mapped[int] = mapped_column(
        ForeignKey("course.id"), primary_key=True, nullable=False
    )
    teacher_id: Mapped[int] = mapped_column(
        ForeignKey("teacher.id"), primary_key=True, nullable=False
    )
    target_hours: Mapped[int] = mapped_column(Integer, default=0)

    course: Mapped[Course] = relationship("Course", back_populates="teacher_allocations")
    teacher: Mapped[Teacher] = relationship("Teacher")

    __table_args__ = (
        CheckConstraint("target_hours >= 0", name="chk_course_teacher_allocation_hours"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"CourseTeacherAllocation<Course {self.course_id} / Teacher {self.teacher_id}"
            f" target={self.target_hours}h>"
        )
