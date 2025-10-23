from datetime import date, datetime, time, timedelta

from . import db
from .models import (
    ClassGroup,
    Course,
    CourseClassLink,
    CourseName,
    Equipment,
    Room,
    Session,
    Student,
    Software,
    Teacher,
    TeacherAvailability,
)


def seed_data() -> None:
    if Teacher.query.count():
        return

    today = date.today()

    python_course_name = CourseName(name="Python Avancé")
    python = Course(
        name=Course.compose_name("TD", python_course_name.name, "S1"),
        description="Programmation avancée en Python",
        session_length_hours=2,
        sessions_required=4,
        course_type="TD",
        semester="S1",
        configured_name=python_course_name,
        requires_computers=True,
        computers_required=20,
    )

    teacher = Teacher(
        name="Alice Martin",
        email="alice@example.com",
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

    python_group_a = CourseName(name="Python Avancé — Groupe A")
    python_group_b = CourseName(name="Python Avancé — Groupe B")

    class_a = ClassGroup(name="Classe A", size=20)
    class_a.students.extend(
        [
            Student(full_name="Emma Dupont", email="emma.dupont@example.com"),
            Student(full_name="Lucas Bernard"),
        ]
    )
    python.class_links.append(CourseClassLink(class_group=class_a))

    db.session.add_all([
        python,
        python_course_name,
        teacher,
        room,
        projector,
        vscode,
        class_a,
        python_group_a,
        python_group_b,
    ])
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
    sample_session.attendees = [class_a]
    db.session.add(sample_session)
    db.session.commit()
