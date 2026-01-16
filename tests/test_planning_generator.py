from datetime import date, time

import pytest

from app.models import ClassGroup, Course, CourseClassLink, Room, Teacher, TeacherAvailability
from app.planning.generator import generate_schedule


def _add_teacher_availability(session, teacher, weekday: int, start: time, end: time) -> None:
    session.add(
        TeacherAvailability(
            teacher=teacher,
            weekday=weekday,
            start_time=start,
            end_time=end,
        )
    )
    session.commit()


def test_generate_schedule_places_session(session):
    teacher = Teacher(name="Bob")
    class_group = ClassGroup(name="INFO2", size=20)
    course = Course(
        name="Physique S1",
        course_type="TD",
        semester="S1",
        session_length_hours=2,
        sessions_required=1,
        sessions_per_week=1,
    )
    course.teachers.append(teacher)
    link = CourseClassLink(class_group=class_group)
    course.class_links.append(link)
    room = Room(name="C201", capacity=30, computers=0)
    session.add_all([teacher, class_group, course, room])
    session.commit()
    _add_teacher_availability(session, teacher, 0, time(8, 0), time(12, 0))

    created = generate_schedule(
        course,
        window_start=date(2025, 9, 1),
        window_end=date(2025, 9, 5),
        allowed_weeks=[(date(2025, 9, 1), date(2025, 9, 5), 1)],
    )

    assert created
    assert created[0].teacher_id == teacher.id
