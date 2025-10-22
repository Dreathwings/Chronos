import unittest
from datetime import date, datetime, time

from app import create_app, db
from app.models import (
    ClassGroup,
    Course,
    CourseClassLink,
    Room,
    Session,
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


class OneHourPlacementTestCase(DatabaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.teacher = Teacher(name="Alice")
        self.room = Room(name="A101", capacity=30)
        self.class_group = ClassGroup(name="INFO1", size=24)
        db.session.add_all([self.teacher, self.room, self.class_group])
        db.session.commit()

        availability = TeacherAvailability(
            teacher=self.teacher,
            weekday=0,
            start_time=time(8, 0),
            end_time=time(13, 0),
        )
        db.session.add(availability)
        db.session.commit()

    def _create_course(self, name: str) -> tuple[Course, CourseClassLink]:
        course = Course(
            name=name,
            course_type="TD",
            session_length_hours=1,
            sessions_required=1,
            semester="S1",
        )
        link = CourseClassLink(class_group=self.class_group)
        link.teacher_a = self.teacher
        course.class_links.append(link)
        course.teachers.append(self.teacher)
        db.session.add(course)
        db.session.commit()
        return course, link

    def test_pairs_one_hour_session_with_existing_block(self) -> None:
        existing_course, _ = self._create_course("TD - Communication - S1")

        existing_session = Session(
            course=existing_course,
            teacher=self.teacher,
            room=self.room,
            class_group=self.class_group,
            start_time=datetime(2025, 9, 8, 10, 15, 0),
            end_time=datetime(2025, 9, 8, 11, 15, 0),
        )
        existing_session.attendees = [self.class_group]
        db.session.add(existing_session)
        db.session.commit()

        new_course, _ = self._create_course("TD - Algorithmique - S1")

        created = generate_schedule(
            new_course,
            window_start=date(2025, 9, 8),
            window_end=date(2025, 9, 12),
        )

        self.assertEqual(len(created), 1)
        generated_session = created[0]
        self.assertEqual(generated_session.start_time, datetime(2025, 9, 8, 9, 0, 0))
        self.assertEqual(generated_session.end_time, datetime(2025, 9, 8, 10, 0, 0))


if __name__ == "__main__":
    unittest.main()
