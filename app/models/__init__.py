"""SQLAlchemy models for Chronos."""
from __future__ import annotations

from sqlalchemy import CheckConstraint, Column, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from ..extensions import db


class Teacher(db.Model):
    __tablename__ = "teachers"

    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False, unique=True)
    max_weekly_load_hrs = Column(Integer, nullable=False, default=20)

    availabilities = relationship(
        "TeacherAvailability", cascade="all, delete-orphan", back_populates="teacher"
    )
    unavailabilities = relationship(
        "TeacherUnavailability",
        cascade="all, delete-orphan",
        back_populates="teacher",
    )
    courses = relationship("Course", back_populates="teacher")

    def __repr__(self) -> str:  # pragma: no cover - repr helper
        return f"<Teacher {self.name}>"


class TeacherAvailability(db.Model):
    __tablename__ = "teacher_availabilities"

    id = Column(Integer, primary_key=True)
    teacher_id = Column(
        Integer, ForeignKey("teachers.id", ondelete="CASCADE"), nullable=False
    )
    weekday = Column(Integer, nullable=False)
    start_time = Column(db.Time, nullable=False)
    end_time = Column(db.Time, nullable=False)

    teacher = relationship("Teacher", back_populates="availabilities")

    __table_args__ = (
        CheckConstraint("weekday BETWEEN 0 AND 6", name="ck_weekday"),
    )


class TeacherUnavailability(db.Model):
    __tablename__ = "teacher_unavailabilities"

    id = Column(Integer, primary_key=True)
    teacher_id = Column(
        Integer, ForeignKey("teachers.id", ondelete="CASCADE"), nullable=False
    )
    date = Column(db.Date, nullable=False)
    start_time = Column(db.Time, nullable=False)
    end_time = Column(db.Time, nullable=False)

    teacher = relationship("Teacher", back_populates="unavailabilities")


class Room(db.Model):
    __tablename__ = "rooms"

    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False, unique=True)
    capacity = Column(Integer, nullable=False)
    building = Column(String(120), nullable=True)

    equipment = relationship(
        "RoomEquipment", cascade="all, delete-orphan", back_populates="room"
    )
    assignments = relationship("Assignment", back_populates="room")

    def __repr__(self) -> str:  # pragma: no cover - repr helper
        return f"<Room {self.name}>"


class RoomEquipment(db.Model):
    __tablename__ = "room_equipment"

    id = Column(Integer, primary_key=True)
    room_id = Column(
        Integer, ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False
    )
    key = Column(String(120), nullable=False)
    value = Column(String(120), nullable=False)

    room = relationship("Room", back_populates="equipment")


class ClassGroup(db.Model):
    __tablename__ = "class_groups"

    id = Column(Integer, primary_key=True)
    code = Column(String(120), nullable=False, unique=True)
    name = Column(String(255), nullable=False)
    size = Column(Integer, nullable=False)
    notes = Column(String(255), nullable=True)

    courses = relationship("Course", back_populates="class_group")

    def __repr__(self) -> str:  # pragma: no cover - repr helper
        return f"<ClassGroup {self.code}>"


class Course(db.Model):
    __tablename__ = "courses"

    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    group_id = Column(
        String(120), ForeignKey("class_groups.code", ondelete="RESTRICT"), nullable=False
    )
    size = Column(Integer, nullable=False)
    teacher_id = Column(Integer, ForeignKey("teachers.id"), nullable=False)
    sessions_count = Column(Integer, nullable=False)
    session_minutes = Column(Integer, nullable=False)
    window_start = Column(db.Date, nullable=False)
    window_end = Column(db.Date, nullable=False)

    teacher = relationship("Teacher", back_populates="courses")
    class_group = relationship("ClassGroup", back_populates="courses")
    requirements = relationship("CourseRequirement", cascade="all, delete-orphan")
    assignments = relationship("Assignment", cascade="all, delete-orphan")


class CourseRequirement(db.Model):
    __tablename__ = "course_requirements"

    id = Column(Integer, primary_key=True)
    course_id = Column(
        Integer, ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    key = Column(String(120), nullable=False)
    value = Column(String(120), nullable=False)

    course = relationship("Course", back_populates="requirements")


class Timeslot(db.Model):
    __tablename__ = "timeslots"

    id = Column(Integer, primary_key=True)
    date = Column(db.Date, nullable=False)
    start_time = Column(db.Time, nullable=False)
    end_time = Column(db.Time, nullable=False)
    minutes = Column(Integer, nullable=False)

    assignments = relationship("Assignment", back_populates="timeslot")


class Assignment(db.Model):
    __tablename__ = "assignments"

    id = Column(Integer, primary_key=True)
    course_id = Column(
        Integer, ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    session_index = Column(Integer, nullable=False)
    timeslot_id = Column(Integer, ForeignKey("timeslots.id"), nullable=False)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=False)
    teacher_id = Column(Integer, ForeignKey("teachers.id"), nullable=False)
    status = Column(String(20), nullable=False, default="scheduled")

    course = relationship("Course", back_populates="assignments")
    room = relationship("Room", back_populates="assignments")
    teacher = relationship("Teacher")
    timeslot = relationship("Timeslot", back_populates="assignments")

    __table_args__ = (
        CheckConstraint("session_index >= 0", name="ck_session_index_positive"),
    )
