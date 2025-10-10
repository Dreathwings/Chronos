"""Seed the database with demo data."""
from __future__ import annotations

from datetime import datetime, timedelta

from flask import Flask

from . import create_app, db
from .models import Course, CourseSession, Material, Room, Software, Teacher


def run(app: Flask | None = None) -> None:
    app = app or create_app()
    with app.app_context():
        db.create_all()

        if Teacher.query.count() == 0:
            teachers = [
                Teacher(first_name="Alice", last_name="Durand", email="alice@example.com"),
                Teacher(first_name="Benoît", last_name="Martin", email="benoit@example.com"),
            ]
            db.session.add_all(teachers)

        if Room.query.count() == 0:
            rooms = [
                Room(name="Salle 101", capacity=30, has_computers=True),
                Room(name="Lab A", capacity=20, has_computers=True, equipment_notes="Projecteur"),
            ]
            db.session.add_all(rooms)

        if Course.query.count() == 0:
            python = Course(
                title="Python avancé",
                description="Programmation orientée objet et tests.",
                sessions_required=4,
                session_duration_hours=3,
                priority=1,
            )
            python.materials = [Material(name="Projecteur")]
            python.software = [Software(name="PyCharm"), Software(name="pytest")]
            db.session.add(python)

            data_science = Course(
                title="Data Science",
                description="Nettoyage de données et visualisation.",
                sessions_required=5,
                session_duration_hours=2,
                priority=2,
            )
            data_science.materials = [Material(name="Tableau blanc")]
            data_science.software = [Software(name="Jupyter"), Software(name="pandas")]
            db.session.add(data_science)

        db.session.commit()

        if CourseSession.query.count() == 0:
            course = Course.query.first()
            teacher = Teacher.query.first()
            room = Room.query.first()
            start = datetime.utcnow().replace(hour=9, minute=0, second=0, microsecond=0)
            for i in range(3):
                session = CourseSession(
                    course=course,
                    teacher=teacher,
                    room=room,
                    start_datetime=start + timedelta(days=i),
                    end_datetime=start + timedelta(days=i, hours=course.session_duration_hours),
                )
                db.session.add(session)
            db.session.commit()


def main() -> None:
    run()


if __name__ == "__main__":
    main()
