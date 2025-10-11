from __future__ import annotations

from datetime import date, datetime, time
from typing import List, Optional

from sqlalchemy import CheckConstraint, Column, Date, DateTime, ForeignKey, Integer, String, Table, Text, Time, UniqueConstraint
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


def default_start_time() -> time:
    return time(8, 0)


def default_end_time() -> time:
    return time(18, 0)


class TimeStampedModel:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Teacher(db.Model, TimeStampedModel):
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    email: Mapped[Optional[str]] = mapped_column(String(255))
    phone: Mapped[Optional[str]] = mapped_column(String(50))
    available_from: Mapped[time] = mapped_column(Time, default=default_start_time)
    available_until: Mapped[time] = mapped_column(Time, default=default_end_time)
    max_hours_per_week: Mapped[int] = mapped_column(Integer, default=20)
    unavailable_dates: Mapped[Optional[str]] = mapped_column(Text)
    notes: Mapped[Optional[str]] = mapped_column(Text)

    sessions: Mapped[List["Session"]] = relationship(back_populates="teacher", cascade="all, delete-orphan")
    courses: Mapped[List["Course"]] = relationship(secondary=course_teacher, back_populates="teachers")

    def is_available_on(self, day: datetime) -> bool:
        if not self.unavailable_dates:
            return True
        unavailable = {d.strip() for d in self.unavailable_dates.split(",") if d.strip()}
        return day.strftime("%Y-%m-%d") not in unavailable

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
    start_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    course: Mapped[Course] = relationship(back_populates="sessions")
    teacher: Mapped[Teacher] = relationship(back_populates="sessions")
    room: Mapped[Room] = relationship(back_populates="sessions")

    __table_args__ = (
        CheckConstraint("end_time > start_time", name="chk_session_time_order"),
        UniqueConstraint("room_id", "start_time", name="uq_room_start_time"),
    )

    def as_event(self) -> dict[str, str]:
        return {
            "id": str(self.id),
            "title": f"{self.course.name} — {self.room.name}",
            "start": self.start_time.isoformat(),
            "end": self.end_time.isoformat(),
            "extendedProps": {
                "teacher": self.teacher.name,
                "course": self.course.name,
                "room": self.room.name,
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
