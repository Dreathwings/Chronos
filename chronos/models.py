"""Additional database models for Chronos incremental planning."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app import db


class PlanningVersion(db.Model):
    """Represents a generated planning version."""

    __tablename__ = "planning_version"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    label: Mapped[str] = mapped_column(String(32), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    sessions: Mapped[list["SessionValidated"]] = relationship(
        "SessionValidated",
        back_populates="version",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"PlanningVersion(label={self.label!r}, revision={self.revision})"


class SessionValidated(db.Model):
    """Validated session bound to a planning version."""

    __tablename__ = "session_validated"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    course_id: Mapped[int] = mapped_column(Integer, nullable=False)
    teacher_id: Mapped[int] = mapped_column(Integer, nullable=False)
    group_id: Mapped[int] = mapped_column(Integer, nullable=False)
    room_id: Mapped[Optional[int]] = mapped_column(Integer)
    start_dt: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end_dt: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    version_id: Mapped[int] = mapped_column(ForeignKey("planning_version.id"), nullable=False)

    version: Mapped[PlanningVersion] = relationship("PlanningVersion", back_populates="sessions")

    def clone_for_version(self, version: PlanningVersion) -> "SessionValidated":
        clone = SessionValidated(
            course_id=self.course_id,
            teacher_id=self.teacher_id,
            group_id=self.group_id,
            room_id=self.room_id,
            start_dt=self.start_dt,
            end_dt=self.end_dt,
            version=version,
        )
        return clone

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            "SessionValidated(" \
            f"course={self.course_id}, teacher={self.teacher_id}, " \
            f"group={self.group_id}, room={self.room_id}, " \
            f"start={self.start_dt}, end={self.end_dt})"
        )


__all__ = ["PlanningVersion", "SessionValidated"]
