from __future__ import annotations

from datetime import date, datetime, time
from math import ceil
from typing import List, Optional, Set

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


COURSE_TYPE_CHOICES = ("CM", "TD", "TP", "SAE")
COURSE_TYPE_LABELS = {
    "CM": "Cours magistral",
    "TD": "Travaux dirigés",
    "TP": "Travaux pratiques",
    "SAE": "Situation d'apprentissage et d'évaluation",
}


class Course(db.Model, TimeStampedModel):
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    session_length_hours: Mapped[int] = mapped_column(Integer, default=2)
    sessions_required: Mapped[int] = mapped_column(Integer, default=1)
    start_date: Mapped[Optional[date]] = mapped_column(Date)
    end_date: Mapped[Optional[date]] = mapped_column(Date)
    priority: Mapped[int] = mapped_column(Integer, default=1)
    course_type: Mapped[str] = mapped_column(String(3), default="CM")

    requires_computers: Mapped[bool] = mapped_column(db.Boolean, default=False)

    teachers: Mapped[List[Teacher]] = relationship(secondary=course_teacher, back_populates="courses")
    softwares: Mapped[List["Software"]] = relationship(secondary=course_software, back_populates="courses")
    equipments: Mapped[List["Equipment"]] = relationship(secondary=course_equipment, back_populates="courses")
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

    __table_args__ = (
        CheckConstraint("session_length_hours > 0", name="chk_session_length_positive"),
        CheckConstraint("sessions_required > 0", name="chk_session_required_positive"),
        CheckConstraint(
            "course_type IN ('CM','TD','TP','SAE')",
            name="chk_course_type_valid",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"Course<{self.id} {self.name}>"

    @property
    def is_tp(self) -> bool:
        return self.course_type == "TP"

    @property
    def is_cm(self) -> bool:
        return self.course_type == "CM"

    @property
    def is_sae(self) -> bool:
        return self.course_type == "SAE"

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
        return self.sessions_required * self.session_length_hours * multiplier


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
        UniqueConstraint("class_group_id", "start_time", name="uq_class_start_time"),
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
        group_suffix = f" — groupe {self.subgroup_label}" if self.subgroup_label else ""
        return f"{self.course.name} — {class_label}{group_suffix} ({room_name})"

    def as_event(self) -> dict[str, str]:
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
        return {
            "id": str(self.id),
            "title": title,
            "start": self.start_time.isoformat(),
            "end": self.end_time.isoformat(),
            "extendedProps": {
                "teacher": self.teacher.name,
                "teacher_email": self.teacher.email,
                "teacher_phone": self.teacher.phone,
                "course": self.course.name,
                "course_type": self.course.course_type,
                "course_type_label": COURSE_TYPE_LABELS.get(
                    self.course.course_type, self.course.course_type
                ),
                "course_description": self.course.description,
                "requires_computers": self.course.requires_computers,
                "course_softwares": course_softwares,
                "room_softwares": room_softwares,
                "missing_softwares": missing_softwares,
                "room": self.room.name,
                "rooms": [self.room.name],
                "class_group": ", ".join(class_names),
                "class_groups": class_names,
                "subgroup": self.subgroup_label,
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
        seen: set[int] = set()
        for session in self.sessions + self.attending_sessions:
            if session.id in seen:
                continue
            if ignore_session_id and session.id == ignore_session_id:
                seen.add(session.id)
                continue
            if self._overlaps(session.start_time, session.end_time, start, end):
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


class CourseClassLink(db.Model):
    __tablename__ = "course_class"

    course_id: Mapped[int] = mapped_column(ForeignKey("course.id"), primary_key=True)
    class_group_id: Mapped[int] = mapped_column(ForeignKey("class_group.id"), primary_key=True)
    group_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    teacher_a_id: Mapped[Optional[int]] = mapped_column(ForeignKey("teacher.id"))
    teacher_b_id: Mapped[Optional[int]] = mapped_column(ForeignKey("teacher.id"))

    course: Mapped[Course] = relationship(back_populates="class_links")
    class_group: Mapped[ClassGroup] = relationship(back_populates="course_links")
    teacher_a: Mapped[Optional[Teacher]] = relationship("Teacher", foreign_keys=[teacher_a_id])
    teacher_b: Mapped[Optional[Teacher]] = relationship("Teacher", foreign_keys=[teacher_b_id])

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
            if label == "B" and self.teacher_b:
                ordered.append(self.teacher_b)
            if self.teacher_a and self.teacher_a not in ordered:
                ordered.append(self.teacher_a)
            if self.teacher_b and self.teacher_b not in ordered:
                ordered.append(self.teacher_b)
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
            return [("A/B", teacher)]
        return [("", teacher)]

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"CourseClassLink<Course {self.course_id} / Class {self.class_group_id} "
            f"groups={self.group_count}>"
        )
