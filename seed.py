from __future__ import annotations

from datetime import datetime, timedelta

from app import create_app
from app.extensions import db
from app.models import Course, Room, Teacher


def seed() -> None:
    app = create_app()
    with app.app_context():
        db.drop_all()
        db.create_all()

        teachers = [
            Teacher(full_name="Alice Martin", email="alice.martin@example.com", department="Mathématiques"),
            Teacher(full_name="Benoît Durand", email="benoit.durand@example.com", department="Physique"),
        ]
        db.session.add_all(teachers)

        rooms = [
            Room(name="Salle A", capacity=30, equipments="Vidéo-projecteur", has_computers=True),
            Room(name="Salle B", capacity=20, equipments="Tableau blanc", has_computers=False),
        ]
        db.session.add_all(rooms)
        db.session.flush()

        now = datetime.now().replace(hour=8, minute=0, second=0, microsecond=0)
        courses = [
            Course(
                name="Analyse 1",
                group_name="A1",
                teacher_id=teachers[0].id,
                room_id=rooms[0].id,
                start_time=now,
                end_time=now + timedelta(hours=2),
                duration_hours=2,
                priority=3,
            ),
            Course(
                name="Physique Quantique",
                group_name="B2",
                teacher_id=teachers[1].id,
                room_id=rooms[1].id,
                start_time=now + timedelta(days=1, hours=1),
                end_time=now + timedelta(days=1, hours=3),
                duration_hours=2,
                priority=2,
            ),
        ]
        db.session.add_all(courses)
        db.session.commit()

        print("Base de données initialisée avec des données de démonstration.")


if __name__ == "__main__":
    seed()
