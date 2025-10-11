from __future__ import annotations

from datetime import time

from app import create_app, db
from app.models import Course, Material, Room, Software, Teacher, TeacherAvailability


def run_seed() -> None:
    app = create_app()
    with app.app_context():
        db.create_all()

        if not Teacher.query.first():
            teachers = [
                Teacher(full_name="Alice Martin", email="alice.martin@example.com", max_hours_per_week=12),
                Teacher(full_name="Bruno Costa", email="bruno.costa@example.com", max_hours_per_week=15),
            ]
            for teacher in teachers:
                db.session.add(teacher)
            db.session.flush()

            availabilities = [
                TeacherAvailability(teacher_id=teachers[0].id, weekday=0, start_time=time(8, 0), end_time=time(16, 0)),
                TeacherAvailability(teacher_id=teachers[1].id, weekday=1, start_time=time(9, 0), end_time=time(17, 0)),
            ]
            db.session.add_all(availabilities)

        if not Material.query.first():
            db.session.add_all(
                [
                    Material(name="Vidéoprojecteur"),
                    Material(name="Tableau blanc"),
                    Material(name="Laboratoire"),
                ]
            )

        if not Software.query.first():
            db.session.add_all(
                [
                    Software(name="Python", version="3.11"),
                    Software(name="Excel", version="365"),
                ]
            )

        db.session.commit()

        if not Room.query.first():
            materials = Material.query.all()
            rooms = [
                Room(name="Salle A", capacity=30, computers=15, materials=materials[:2]),
                Room(name="Salle B", capacity=20, computers=0, materials=materials[1:]),
            ]
            db.session.add_all(rooms)

        if not Course.query.first():
            softwares = Software.query.all()
            courses = [
                Course(
                    title="Introduction à la programmation",
                    duration_hours=2,
                    session_count=4,
                    priority=3,
                    required_capacity=20,
                    requires_computers=True,
                    softwares=[softwares[0]] if softwares else [],
                ),
                Course(
                    title="Analyse de données",
                    duration_hours=2,
                    session_count=3,
                    priority=2,
                    required_capacity=15,
                    requires_computers=True,
                    softwares=softwares,
                ),
            ]
            db.session.add_all(courses)

        db.session.commit()
        print("Base de données initialisée.")


if __name__ == "__main__":
    run_seed()
