"""Database models for Chronos."""
from __future__ import annotations

from datetime import date, datetime, time

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import db


class TimestampMixin:
    """Mixin providing created/updated timestamps."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )


class Teacher(db.Model, TimestampMixin):
    __tablename__ = "teachers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    first_name: Mapped[str] = mapped_column(String(80), nullable=False)
    last_name: Mapped[str] = mapped_column(String(80), nullable=False)
    email: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    max_hours_per_week: Mapped[int] = mapped_column(Integer, default=20)
    notes: Mapped[str | None] = mapped_column(Text())

    availabilities: Mapped[list[TeacherAvailability]] = relationship(
        back_populates="teacher", cascade="all, delete-orphan"
    )
    unavailabilities: Mapped[list[TeacherUnavailability]] = relationship(
        back_populates="teacher", cascade="all, delete-orphan"
    )
    sessions: Mapped[list[CourseSession]] = relationship(back_populates="teacher")

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Teacher {self.full_name}>"

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"


class TeacherAvailability(db.Model):
    __tablename__ = "teacher_availabilities"
    __table_args__ = (
        CheckConstraint("weekday >= 0 AND weekday <= 6", name="chk_weekday_range"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("teachers.id"), nullable=False)
    weekday: Mapped[int] = mapped_column(Integer, nullable=False)
    start_time: Mapped[time] = mapped_column(nullable=False)
    end_time: Mapped[time] = mapped_column(nullable=False)

    teacher: Mapped[Teacher] = relationship(back_populates="availabilities")


class TeacherUnavailability(db.Model):
    __tablename__ = "teacher_unavailabilities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("teachers.id"), nullable=False)
    date: Mapped[date] = mapped_column(Date(), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text())

    teacher: Mapped[Teacher] = relationship(back_populates="unavailabilities")


class Room(db.Model, TimestampMixin):
    __tablename__ = "rooms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    has_computers: Mapped[bool] = mapped_column(default=False)
    equipment_notes: Mapped[str | None] = mapped_column(Text())

    sessions: Mapped[list[CourseSession]] = relationship(back_populates="room")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Room {self.name}>"


class Material(db.Model):
    __tablename__ = "materials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)

    courses: Mapped[list[Course]] = relationship(
        secondary="course_materials", back_populates="materials"
    )


class Software(db.Model):
    __tablename__ = "software"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)

    courses: Mapped[list[Course]] = relationship(
        secondary="course_software", back_populates="software"
    )


class Course(db.Model, TimestampMixin):
    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text())
    sessions_required: Mapped[int] = mapped_column(Integer, default=1)
    session_duration_hours: Mapped[int] = mapped_column(Integer, default=2)
    priority: Mapped[int] = mapped_column(Integer, default=1)
    start_date: Mapped[date | None] = mapped_column(Date())
    end_date: Mapped[date | None] = mapped_column(Date())

    materials: Mapped[list[Material]] = relationship(
        secondary="course_materials", back_populates="courses"
    )
    software: Mapped[list[Software]] = relationship(
        secondary="course_software", back_populates="courses"
    )
    sessions: Mapped[list[CourseSession]] = relationship(back_populates="course")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Course {self.title}>"


class CourseMaterial(db.Model):
    __tablename__ = "course_materials"

    course_id: Mapped[int] = mapped_column(
        ForeignKey("courses.id"), primary_key=True, nullable=False
    )
    material_id: Mapped[int] = mapped_column(
        ForeignKey("materials.id"), primary_key=True, nullable=False
    )


class CourseSoftware(db.Model):
    __tablename__ = "course_software"

    course_id: Mapped[int] = mapped_column(
        ForeignKey("courses.id"), primary_key=True, nullable=False
    )
    software_id: Mapped[int] = mapped_column(
        ForeignKey("software.id"), primary_key=True, nullable=False
    )


class CourseSession(db.Model, TimestampMixin):
    __tablename__ = "course_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), nullable=False)
    teacher_id: Mapped[int | None] = mapped_column(ForeignKey("teachers.id"))
    room_id: Mapped[int | None] = mapped_column(ForeignKey("rooms.id"))
    start_datetime: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_datetime: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    course: Mapped[Course] = relationship(back_populates="sessions")
    teacher: Mapped[Teacher | None] = relationship(back_populates="sessions")
    room: Mapped[Room | None] = relationship(back_populates="sessions")

    def as_fullcalendar_event(self) -> dict[str, str | int]:
        """Return an event payload for FullCalendar."""
        title_parts = [self.course.title]
        if self.teacher:
            title_parts.append(self.teacher.full_name)
        if self.room:
            title_parts.append(self.room.name)
        return {
            "id": self.id,
            "title": " — ".join(title_parts),
            "start": self.start_datetime.isoformat(),
            "end": self.end_datetime.isoformat(),
            "extendedProps": {
                "courseId": self.course_id,
                "teacherId": self.teacher_id,
                "roomId": self.room_id,
            },
        }
