from datetime import date, datetime, time, timedelta

from . import db
from .models import (
    ClassGroup,
    Course,
    Equipment,
    Room,
    Session,
    Software,
    Teacher,
    TeacherAvailability,
)


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

    class_a = ClassGroup(name="Classe A", size=20)
    python.classes.append(class_a)

    db.session.add_all([python, teacher, room, projector, vscode, class_a])
    db.session.flush()

    sample_start = datetime.combine(today, time(8, 0))
    sample_end = sample_start + timedelta(hours=2)
    sample_session = Session(
        course=python,
        teacher=teacher,
        room=room,
        class_group=class_a,
        start_time=sample_start,
        end_time=sample_end,
    )
    db.session.add(sample_session)
    db.session.commit()
