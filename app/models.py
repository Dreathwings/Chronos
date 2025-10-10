from __future__ import annotations

from datetime import datetime, time

from sqlalchemy import CheckConstraint, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .extensions import db


def default_start() -> datetime:
    return datetime.now().replace(hour=8, minute=0, second=0, microsecond=0)


def default_end() -> datetime:
    return datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)


class Teacher(db.Model):
    __tablename__ = "teachers"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(db.String(120), nullable=False)
    email: Mapped[str] = mapped_column(db.String(255), unique=True, nullable=False)
    department: Mapped[str | None] = mapped_column(db.String(120))

    courses: Mapped[list["Course"]] = relationship(back_populates="teacher", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"Teacher({self.full_name!r})"


class Room(db.Model):
    __tablename__ = "rooms"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(db.String(80), unique=True, nullable=False)
    capacity: Mapped[int] = mapped_column(default=20)
    equipments: Mapped[str | None] = mapped_column(db.Text)
    has_computers: Mapped[bool] = mapped_column(default=False)

    courses: Mapped[list["Course"]] = relationship(back_populates="room", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"Room({self.name!r})"


class Course(db.Model):
    __tablename__ = "courses"
    __table_args__ = (
        UniqueConstraint("name", "group_name", name="uq_course_name_group"),
        CheckConstraint("duration_hours BETWEEN 1 AND 4", name="ck_course_duration"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(db.String(120), nullable=False)
    group_name: Mapped[str] = mapped_column(db.String(120), default="A1")
    teacher_id: Mapped[int] = mapped_column(ForeignKey("teachers.id"), nullable=False)
    room_id: Mapped[int | None] = mapped_column(ForeignKey("rooms.id"))
    start_time: Mapped[datetime] = mapped_column(default=default_start)
    end_time: Mapped[datetime] = mapped_column(default=default_end)
    duration_hours: Mapped[int] = mapped_column(default=1)
    software_required: Mapped[str | None] = mapped_column(db.String(255))
    priority: Mapped[int] = mapped_column(default=1)

    teacher: Mapped[Teacher] = relationship(back_populates="courses")
    room: Mapped[Room | None] = relationship(back_populates="courses")

    def __repr__(self) -> str:
        return f"Course({self.name!r})"

    @property
    def start_time_hour(self) -> time:
        return self.start_time.time()

    @property
    def end_time_hour(self) -> time:
        return self.end_time.time()

    def to_calendar_dict(self) -> dict[str, str]:
        return {
            "title": self.name,
            "start": self.start_time.strftime("%Y-%m-%dT%H:%M"),
            "end": self.end_time.strftime("%Y-%m-%dT%H:%M"),
            "teacher": self.teacher.full_name,
            "room": self.room.name if self.room else "TBD",
        }
