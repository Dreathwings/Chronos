from datetime import date, timedelta

from . import db
from .models import Course, Equipment, Room, Software, Teacher


def seed_data() -> None:
    if Teacher.query.count():
        return

    today = date.today()

    python = Course(
        name="Python Avancé",
        description="Programmation avancée en Python",
        expected_students=18,
        session_length_hours=2,
        sessions_required=4,
        start_date=today,
        end_date=today + timedelta(days=10),
        priority=1,
        requires_computers=True,
    )

    teacher = Teacher(
        name="Alice Martin",
        email="alice@example.com",
        max_hours_per_week=12,
        unavailable_dates="",
    )

    room = Room(name="Salle 101", capacity=24, computers=20)

    projector = Equipment(name="Vidéo-projecteur")
    python.equipments.append(projector)
    room.equipments.append(projector)

    vscode = Software(name="VS Code")
    python.softwares.append(vscode)
    room.softwares.append(vscode)

    python.teachers.append(teacher)

    db.session.add_all([python, teacher, room, projector, vscode])
    db.session.commit()
