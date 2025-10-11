from datetime import date, time, timedelta

from . import db
from .models import Course, Equipment, Room, Software, Teacher, TeacherAvailability


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

    default_slots = [
        (time(8, 0), time(10, 0)),
        (time(10, 15), time(12, 15)),
        (time(13, 30), time(15, 30)),
        (time(15, 45), time(17, 45)),
    ]
    for weekday in range(5):
        for start, end in default_slots:
            teacher.availabilities.append(
                TeacherAvailability(weekday=weekday, start_time=start, end_time=end)
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
