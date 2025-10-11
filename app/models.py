from __future__ import annotations

from datetime import date, datetime, time

from sqlalchemy import (
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    Time,
    Boolean,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import db


room_materials = Table(
    "room_materials",
    db.metadata,
    Column("room_id", ForeignKey("room.id"), primary_key=True),
    Column("material_id", ForeignKey("material.id"), primary_key=True),
)

course_materials = Table(
    "course_materials",
    db.metadata,
    Column("course_id", ForeignKey("course.id"), primary_key=True),
    Column("material_id", ForeignKey("material.id"), primary_key=True),
)

course_softwares = Table(
    "course_softwares",
    db.metadata,
    Column("course_id", ForeignKey("course.id"), primary_key=True),
    Column("software_id", ForeignKey("software.id"), primary_key=True),
)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, onupdate=datetime.utcnow)


class Teacher(db.Model, TimestampMixin):
    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    max_hours_per_week: Mapped[int] = mapped_column(Integer, default=20)

    availabilities: Mapped[list["TeacherAvailability"]] = relationship(
        back_populates="teacher", cascade="all, delete-orphan"
    )
    unavailabilities: Mapped[list["TeacherUnavailability"]] = relationship(
        back_populates="teacher", cascade="all, delete-orphan"
    )
    sessions: Mapped[list["CourseSession"]] = relationship(
        back_populates="teacher", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - repr helper
        return f"Teacher(id={self.id}, name={self.full_name!r})"


class TeacherAvailability(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("teacher.id"), nullable=False)
    weekday: Mapped[int] = mapped_column(Integer, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)

    teacher: Mapped[Teacher] = relationship(back_populates="availabilities")

    __table_args__ = (
        CheckConstraint("weekday BETWEEN 0 AND 6", name="ck_availability_weekday"),
        CheckConstraint("start_time < end_time", name="ck_availability_time"),
    )


class TeacherUnavailability(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("teacher.id"), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[str] = mapped_column(String(255), default="")

    teacher: Mapped[Teacher] = relationship(back_populates="unavailabilities")


class Material(db.Model, TimestampMixin):
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(String(255), default="")

    rooms: Mapped[list["Room"]] = relationship(secondary=room_materials, back_populates="materials")
    courses: Mapped[list["Course"]] = relationship(secondary=course_materials, back_populates="materials")


class Software(db.Model, TimestampMixin):
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    version: Mapped[str] = mapped_column(String(40), default="latest")

    courses: Mapped[list["Course"]] = relationship(secondary=course_softwares, back_populates="softwares")


class Room(db.Model, TimestampMixin):
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, default=30)
    computers: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[str] = mapped_column(String(255), default="")

    materials: Mapped[list[Material]] = relationship(secondary=room_materials, back_populates="rooms")
    sessions: Mapped[list["CourseSession"]] = relationship(
        back_populates="room", cascade="all, delete-orphan"
    )


class Course(db.Model, TimestampMixin):
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    duration_hours: Mapped[int] = mapped_column(Integer, default=2)
    session_count: Mapped[int] = mapped_column(Integer, default=1)
    priority: Mapped[int] = mapped_column(Integer, default=1)
    required_capacity: Mapped[int] = mapped_column(Integer, default=20)
    requires_computers: Mapped[bool] = mapped_column(Boolean, default=False)

    materials: Mapped[list[Material]] = relationship(secondary=course_materials, back_populates="courses")
    softwares: Mapped[list[Software]] = relationship(secondary=course_softwares, back_populates="courses")
    sessions: Mapped[list["CourseSession"]] = relationship(
        back_populates="course", cascade="all, delete-orphan"
    )


class CourseSession(db.Model, TimestampMixin):
    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("course.id"), nullable=False)
    teacher_id: Mapped[int | None] = mapped_column(ForeignKey("teacher.id"))
    room_id: Mapped[int | None] = mapped_column(ForeignKey("room.id"))
    start: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    course: Mapped[Course] = relationship(back_populates="sessions")
    teacher: Mapped[Teacher | None] = relationship(back_populates="sessions")
    room: Mapped[Room | None] = relationship(back_populates="sessions")

    __table_args__ = (CheckConstraint("start < end", name="ck_session_time"),)


__all__ = [
    "Teacher",
    "TeacherAvailability",
    "TeacherUnavailability",
    "Material",
    "Software",
    "Room",
    "Course",
    "CourseSession",
]
