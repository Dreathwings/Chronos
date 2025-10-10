from __future__ import annotations

from datetime import date, time, timedelta
from typing import Optional

from sqlalchemy import CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .extensions import db


class Teacher(db.Model):
    __tablename__ = "teachers"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(db.String(120), nullable=False)
    email: Mapped[str] = mapped_column(db.String(120), unique=True, nullable=False)
    phone_number: Mapped[Optional[str]] = mapped_column(db.String(30))
    availability: Mapped[Optional[str]] = mapped_column(db.Text)
    max_weekly_hours: Mapped[int] = mapped_column(default=20)

    courses: Mapped[list[Course]] = relationship(
        "Course", back_populates="teacher", cascade="all, delete-orphan"
    )
    sessions: Mapped[list[CourseSession]] = relationship(
        "CourseSession", back_populates="teacher"
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"Teacher(id={self.id}, name={self.full_name!r})"


class Room(db.Model):
    __tablename__ = "rooms"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(db.String(120), unique=True, nullable=False)
    capacity: Mapped[int] = mapped_column(default=20)
    location: Mapped[Optional[str]] = mapped_column(db.String(120))
    equipments: Mapped[Optional[str]] = mapped_column(db.Text)
    has_computers: Mapped[bool] = mapped_column(default=False)

    courses: Mapped[list[Course]] = relationship(
        "Course", back_populates="room", cascade="all, delete-orphan"
    )
    sessions: Mapped[list[CourseSession]] = relationship(
        "CourseSession", back_populates="room"
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"Room(id={self.id}, name={self.name!r})"


class Course(db.Model):
    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(db.String(30), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(db.String(120), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(db.Text)
    duration_hours: Mapped[int] = mapped_column(default=1)
    start_date: Mapped[Optional[date]] = mapped_column()
    end_date: Mapped[Optional[date]] = mapped_column()
    group_size: Mapped[int] = mapped_column(default=10)
    required_equipments: Mapped[Optional[str]] = mapped_column(db.Text)
    priority: Mapped[int] = mapped_column(default=1)

    teacher_id: Mapped[Optional[int]] = mapped_column(db.ForeignKey("teachers.id"))
    room_id: Mapped[Optional[int]] = mapped_column(db.ForeignKey("rooms.id"))

    teacher: Mapped[Optional[Teacher]] = relationship("Teacher", back_populates="courses")
    room: Mapped[Optional[Room]] = relationship("Room", back_populates="courses")
    sessions: Mapped[list[CourseSession]] = relationship(
        "CourseSession",
        back_populates="course",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        CheckConstraint("duration_hours > 0", name="ck_course_duration_positive"),
        CheckConstraint("group_size > 0", name="ck_course_group_size_positive"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"Course(id={self.id}, code={self.code!r})"


class CourseSession(db.Model):
    __tablename__ = "course_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(db.ForeignKey("courses.id"), nullable=False)
    teacher_id: Mapped[int] = mapped_column(db.ForeignKey("teachers.id"), nullable=False)
    room_id: Mapped[int] = mapped_column(db.ForeignKey("rooms.id"), nullable=False)

    day_of_week: Mapped[int] = mapped_column(default=0)  # 0 = Monday
    start_time: Mapped[time] = mapped_column(nullable=False)
    end_time: Mapped[time] = mapped_column(nullable=False)

    course: Mapped[Course] = relationship("Course", back_populates="sessions")
    teacher: Mapped[Teacher] = relationship("Teacher", back_populates="sessions")
    room: Mapped[Room] = relationship("Room", back_populates="sessions")

    __table_args__ = (
        CheckConstraint("day_of_week >= 0 AND day_of_week <= 6", name="ck_session_day"),
        CheckConstraint("start_time < end_time", name="ck_session_time_order"),
    )

    @property
    def duration(self) -> timedelta:
        start_delta = timedelta(hours=self.start_time.hour, minutes=self.start_time.minute)
        end_delta = timedelta(hours=self.end_time.hour, minutes=self.end_time.minute)
        return end_delta - start_delta

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"CourseSession(id={self.id}, course_id={self.course_id}, day={self.day_of_week},"
            f" start={self.start_time})"
        )
