from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Iterable, List, Optional, Tuple

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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import db


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


course_class = Table(
    "course_class",
    db.Model.metadata,
    Column("course_id", ForeignKey("course.id"), primary_key=True),
    Column("class_group_id", ForeignKey("class_group.id"), primary_key=True),
)


def default_start_time() -> time:
    return time(8, 0)


def default_end_time() -> time:
    return time(18, 0)


class TimeStampedModel:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


def _normalize_unavailability_tokens(raw: str | None) -> list[str]:
    if not raw:
        return []
    tokens = raw.replace("\n", ",").split(",")
    return [token.strip() for token in tokens if token.strip()]


def parse_teacher_unavailability(
    raw: str | None,
) -> List[Tuple[datetime, datetime]]:
    """Return the list of unavailability windows for a teacher."""

    entries: List[Tuple[datetime, datetime]] = []
    for token in _normalize_unavailability_tokens(raw):
        if " " not in token:
            try:
                day = datetime.strptime(token, "%Y-%m-%d").date()
            except ValueError:
                continue
            start_dt = datetime.combine(day, time.min)
            entries.append((start_dt, start_dt + timedelta(days=1)))
            continue

        try:
            date_part, times_part = token.split(" ", 1)
            day = datetime.strptime(date_part, "%Y-%m-%d").date()
        except ValueError:
            continue

        try:
            start_str, end_str = (value.strip() for value in times_part.split("-", 1))
            start_time = datetime.strptime(start_str, "%H:%M").time()
            end_time = datetime.strptime(end_str, "%H:%M").time()
        except (ValueError, TypeError):
            continue

        if end_time <= start_time:
            continue

        start_dt = datetime.combine(day, start_time)
        end_dt = datetime.combine(day, end_time)
        entries.append((start_dt, end_dt))

    entries.sort(key=lambda entry: entry[0])
    return entries


def serialize_teacher_unavailability(
    entries: Iterable[Tuple[datetime, datetime]]
) -> str:
    tokens: list[str] = []
    for start_dt, end_dt in entries:
        if end_dt <= start_dt:
            continue
        if start_dt.time() == time.min and end_dt - start_dt >= timedelta(days=1):
            tokens.append(start_dt.strftime("%Y-%m-%d"))
        else:
            tokens.append(
                f"{start_dt.strftime('%Y-%m-%d')} {start_dt.strftime('%H:%M')}-{end_dt.strftime('%H:%M')}"
            )
    return "\n".join(tokens)


class Teacher(db.Model, TimeStampedModel):
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    email: Mapped[Optional[str]] = mapped_column(String(255))
    phone: Mapped[Optional[str]] = mapped_column(String(50))
    max_hours_per_week: Mapped[int] = mapped_column(Integer, default=20)
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

    def unavailability_windows(self) -> List[Tuple[datetime, datetime]]:
        return parse_teacher_unavailability(self.unavailable_dates)

    def is_available_on(self, day: datetime | date) -> bool:
        target_date = day.date() if isinstance(day, datetime) else day
        if target_date.weekday() >= 5:
            return False
        for start_dt, end_dt in self.unavailability_windows():
            if start_dt.date() != target_date:
                continue
            if start_dt.time() == time.min and end_dt - start_dt >= timedelta(days=1):
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
                break
        if coverage < target_end:
            return False
        for window_start, window_end in self.unavailability_windows():
            if max(window_start, start) < min(window_end, end):
                return False
        return True

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

    def __repr__(self) -> str:  # pragma: no cover
        return f"Room<{self.id} {self.name}>"


class Course(db.Model, TimeStampedModel):
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    expected_students: Mapped[int] = mapped_column(Integer, default=10)
    session_length_hours: Mapped[int] = mapped_column(Integer, default=2)
    sessions_required: Mapped[int] = mapped_column(Integer, default=1)
    start_date: Mapped[Optional[date]] = mapped_column(Date)
    end_date: Mapped[Optional[date]] = mapped_column(Date)
    priority: Mapped[int] = mapped_column(Integer, default=1)

    requires_computers: Mapped[bool] = mapped_column(db.Boolean, default=False)

    teachers: Mapped[List[Teacher]] = relationship(secondary=course_teacher, back_populates="courses")
    softwares: Mapped[List["Software"]] = relationship(secondary=course_software, back_populates="courses")
    equipments: Mapped[List["Equipment"]] = relationship(secondary=course_equipment, back_populates="courses")
    classes: Mapped[List["ClassGroup"]] = relationship(secondary=course_class, back_populates="courses")
    sessions: Mapped[List["Session"]] = relationship(back_populates="course", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("session_length_hours > 0", name="chk_session_length_positive"),
        CheckConstraint("sessions_required > 0", name="chk_session_required_positive"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"Course<{self.id} {self.name}>"


class Session(db.Model, TimeStampedModel):
    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("course.id"), nullable=False)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("teacher.id"), nullable=False)
    room_id: Mapped[int] = mapped_column(ForeignKey("room.id"), nullable=False)
    class_group_id: Mapped[int] = mapped_column(ForeignKey("class_group.id"), nullable=False)
    start_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    course: Mapped[Course] = relationship(back_populates="sessions")
    teacher: Mapped[Teacher] = relationship(back_populates="sessions")
    room: Mapped[Room] = relationship(back_populates="sessions")
    class_group: Mapped["ClassGroup"] = relationship(back_populates="sessions")

    __table_args__ = (
        CheckConstraint("end_time > start_time", name="chk_session_time_order"),
        UniqueConstraint("room_id", "start_time", name="uq_room_start_time"),
        UniqueConstraint("class_group_id", "start_time", name="uq_class_start_time"),
    )

    def as_event(self) -> dict[str, str]:
        title = f"{self.course.name} — {self.class_group.name} ({self.room.name})"
        return {
            "id": str(self.id),
            "title": title,
            "start": self.start_time.isoformat(),
            "end": self.end_time.isoformat(),
            "extendedProps": {
                "teacher": self.teacher.name,
                "course": self.course.name,
                "room": self.room.name,
                "class_group": self.class_group.name,
            },
        }


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


class ClassGroup(db.Model, TimeStampedModel):
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150), unique=True, nullable=False)
    size: Mapped[int] = mapped_column(Integer, default=20)
    unavailable_dates: Mapped[Optional[str]] = mapped_column(Text)
    notes: Mapped[Optional[str]] = mapped_column(Text)

    courses: Mapped[List[Course]] = relationship(secondary=course_class, back_populates="classes")
    sessions: Mapped[List[Session]] = relationship(
        back_populates="class_group", cascade="all, delete-orphan"
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
        if target_date.strftime("%Y-%m-%d") in self._unavailable_set():
            return False
        return True

    def is_available_during(
        self, start: datetime, end: datetime, *, ignore_session_id: Optional[int] = None
    ) -> bool:
        if not self.is_available_on(start):
            return False
        for session in self.sessions:
            if ignore_session_id and session.id == ignore_session_id:
                continue
            if self._overlaps(session.start_time, session.end_time, start, end):
                return False
        return True

    def __repr__(self) -> str:  # pragma: no cover
        return f"ClassGroup<{self.id} {self.name}>"
