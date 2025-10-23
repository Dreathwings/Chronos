import unittest
from datetime import date, time

from app import create_app, db
from app.models import (
    ClassGroup,
    Course,
    CourseClassLink,
    Room,
    Teacher,
    TeacherAvailability,
)
from app.scheduler import generate_schedule
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


class SaeSplitSchedulingTestCase(DatabaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.teacher = Teacher(name="Alice")
        self.room = Room(name="SAE-1", capacity=28)
        self.class_group = ClassGroup(name="INFO1", size=26)
        db.session.add_all([self.teacher, self.room, self.class_group])
        db.session.commit()

        for weekday in (0, 1):  # Monday and Tuesday, 08:00 → 10:00
            availability = TeacherAvailability(
                teacher=self.teacher,
                weekday=weekday,
                start_time=time(8, 0),
                end_time=time(10, 0),
            )
            db.session.add(availability)
        db.session.commit()

    def _create_course(self, allow_split: bool) -> Course:
        course = Course(
            name="SAE - Gestion de projet - S1",
            course_type="SAE",
            session_length_hours=4,
            sessions_required=1,
            semester="S1",
            sae_split_sessions=allow_split,
        )
        link = CourseClassLink(class_group=self.class_group)
        link.teacher_a = self.teacher
        course.class_links.append(link)
        course.teachers.append(self.teacher)
        db.session.add(course)
        db.session.commit()
        return course

    def test_split_option_allows_dispatch_across_week(self) -> None:
        course = self._create_course(True)

        created = generate_schedule(
            course,
            window_start=date(2025, 9, 8),
            window_end=date(2025, 9, 9),
        )

        self.assertEqual(len(created), 2)
        session_days = sorted(session.start_time.date() for session in created)
        self.assertEqual(session_days, [date(2025, 9, 8), date(2025, 9, 9)])
        for session in created:
            self.assertEqual(session.duration_hours, 2)

    def test_default_requires_four_hour_block(self) -> None:
        course = self._create_course(False)

        with self.assertRaises(ValueError):
            generate_schedule(
                course,
                window_start=date(2025, 9, 8),
                window_end=date(2025, 9, 9),
            )


if __name__ == "__main__":
    unittest.main()
