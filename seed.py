from __future__ import annotations

from datetime import date

from app import create_app
from app.extensions import db
from app.models import Course, Room, Teacher

app = create_app()


def ensure_sample_data() -> None:
    if Teacher.query.first():
        return

    teachers = [
        Teacher(full_name="Alice Martin", email="alice@example.com", max_weekly_hours=18),
        Teacher(full_name="Bruno Leblanc", email="bruno@example.com", max_weekly_hours=20),
        Teacher(full_name="Chloé Dupont", email="chloe@example.com", max_weekly_hours=22),
    ]
    rooms = [
        Room(name="Salle A", capacity=24, equipments="Projecteur, Tableau blanc"),
        Room(name="Laboratoire 1", capacity=18, equipments="PC, Tableau blanc", has_computers=True),
        Room(name="Amphi 3", capacity=60, equipments="Projecteur, Sonorisation"),
    ]
    db.session.add_all(teachers + rooms)
    db.session.commit()

    courses = [
        Course(
            code="ALG101",
            title="Algèbre linéaire",
            description="Introduction aux systèmes linéaires",
            duration_hours=2,
            group_size=24,
            required_equipments="Tableau blanc",
            priority=2,
            teacher=teachers[0],
            room=rooms[0],
            start_date=date.today(),
            end_date=date.today(),
        ),
        Course(
            code="PRG201",
            title="Programmation Python",
            description="Programmation orientée objet",
            duration_hours=2,
            group_size=18,
            required_equipments="PC",
            priority=1,
            teacher=teachers[1],
            room=rooms[1],
            start_date=date.today(),
            end_date=date.today(),
        ),
        Course(
            code="PME150",
            title="Gestion de projet",
            description="Méthodologies agiles",
            duration_hours=1,
            group_size=30,
            required_equipments="Projecteur",
            priority=5,
            teacher=teachers[2],
            room=rooms[2],
            start_date=date.today(),
            end_date=date.today(),
        ),
    ]
    db.session.add_all(courses)
    db.session.commit()


if __name__ == "__main__":
    with app.app_context():
        ensure_sample_data()
        print("Données de démonstration insérées.")
