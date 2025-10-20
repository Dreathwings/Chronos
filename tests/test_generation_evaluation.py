import unittest
from datetime import datetime, time

from app import create_app, db
from app.models import (
    ClassGroup,
    Course,
    CourseClassLink,
    CourseName,
    Room,
    Session,
    Teacher,
    TeacherAvailability,
)
from app.routes import _evaluate_course_generation
from config import TestConfig


class DatabaseTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.app = create_app(TestConfig)
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

    def tearDown(self) -> None:
        db.session.remove()
        db.drop_all()
        self.app_context.pop()


class GenerationEvaluationTestCase(DatabaseTestCase):
    def _create_course_setup(self, *, sessions_required: int = 2) -> Course:
        base_name = CourseName(name="Maths")
        course = Course(
            name=Course.compose_name("TD", base_name.name, "S1"),
            course_type="TD",
            session_length_hours=2,
            sessions_required=sessions_required,
            semester="S1",
            configured_name=base_name,
        )
        class_group = ClassGroup(name="INFO1", size=24)
        link = CourseClassLink(class_group=class_group)
        course.class_links.append(link)

        teacher = Teacher(name="Alice")
        room = Room(name="B101", capacity=30)

        course.teachers.append(teacher)
        db.session.add_all([base_name, course, class_group, teacher, room])
        db.session.commit()

        availabilities = [
            TeacherAvailability(
                teacher=teacher,
                weekday=weekday,
                start_time=time(8, 0),
                end_time=time(18, 0),
            )
            for weekday in range(5)
        ]
        db.session.add_all(availabilities)
        db.session.commit()

        return db.session.get(Course, course.id)

    def test_course_with_valid_sessions_is_successful(self) -> None:
        course = self._create_course_setup(sessions_required=1)
        teacher = course.teachers[0]
        room = Room.query.first()
        class_group = course.class_links[0].class_group

        session = Session(
            course=course,
            teacher=teacher,
            room=room,
            class_group=class_group,
            start_time=datetime(2024, 1, 8, 8, 0, 0),
            end_time=datetime(2024, 1, 8, 10, 0, 0),
        )
        session.attendees = [class_group]
        db.session.add(session)
        db.session.commit()

        refreshed = db.session.get(Course, course.id)
        result = _evaluate_course_generation(refreshed)

        self.assertEqual(result["status"], "success")
        self.assertGreaterEqual(refreshed.scheduled_hours, 2)
        self.assertTrue(any("planifiées" in message for message in result["messages"]))

    def test_missing_hours_triggers_warning(self) -> None:
        course = self._create_course_setup()
        refreshed = db.session.get(Course, course.id)

        result = _evaluate_course_generation(refreshed)

        self.assertEqual(result["status"], "warning")
        self.assertTrue(any("Heures manquantes" in message for message in result["messages"]))

    def test_constraint_violation_marks_error(self) -> None:
        course = self._create_course_setup(sessions_required=1)
        teacher = course.teachers[0]
        room = Room.query.first()
        class_group = course.class_links[0].class_group

        session = Session(
            course=course,
            teacher=teacher,
            room=room,
            class_group=class_group,
            start_time=datetime(2024, 1, 13, 8, 0, 0),
            end_time=datetime(2024, 1, 13, 10, 0, 0),
        )
        session.attendees = [class_group]
        db.session.add(session)
        db.session.commit()

        refreshed = db.session.get(Course, course.id)
        result = _evaluate_course_generation(refreshed)

        self.assertEqual(result["status"], "error")
        self.assertTrue(any("lundi au vendredi" in message for message in result["messages"]))


if __name__ == "__main__":
    unittest.main()
