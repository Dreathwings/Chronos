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
            end_time=time(18, 0),
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
        course.set_teacher_hours(self.teacher, course.total_required_hours)
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
            start_time=datetime(2025, 9, 8, 13, 30, 0),
            end_time=datetime(2025, 9, 8, 14, 30, 0),
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
        self.assertEqual(
            generated_session.start_time, datetime(2025, 9, 8, 14, 30, 0)
        )
        self.assertEqual(
            generated_session.end_time, datetime(2025, 9, 8, 15, 30, 0)
        )

    def test_does_not_pair_across_break(self) -> None:
        existing_course, _ = self._create_course("TD - Bases de données - S1")

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
        self.assertEqual(
            generated_session.start_time, datetime(2025, 9, 8, 11, 15, 0)
        )
        self.assertEqual(
            generated_session.end_time, datetime(2025, 9, 8, 12, 15, 0)
        )

    def test_warns_when_one_hour_sessions_not_consecutive(self) -> None:
        course, _ = self._create_course("TD - Programmation - S1")

        first_session = Session(
            course=course,
            teacher=self.teacher,
            room=self.room,
            class_group=self.class_group,
            start_time=datetime(2025, 9, 8, 8, 0, 0),
            end_time=datetime(2025, 9, 8, 9, 0, 0),
        )
        second_session = Session(
            course=course,
            teacher=self.teacher,
            room=self.room,
            class_group=self.class_group,
            start_time=datetime(2025, 9, 8, 10, 15, 0),
            end_time=datetime(2025, 9, 8, 11, 15, 0),
        )
        for session in (first_session, second_session):
            session.attendees = [self.class_group]
            db.session.add(session)
        db.session.commit()

        created = generate_schedule(
            course,
            window_start=date(2025, 9, 8),
            window_end=date(2025, 9, 12),
        )

        self.assertEqual(created, [])
        db.session.flush()
        log = course.latest_generation_log
        self.assertIsNotNone(log)
        self.assertEqual(log.status, "warning")

    def test_warns_for_cm_non_consecutive_sessions(self) -> None:
        second_group = ClassGroup(name="INFO2", size=26)
        db.session.add(second_group)
        db.session.commit()

        course = Course(
            name="CM - Réseaux - S1",
            course_type="CM",
            session_length_hours=1,
            sessions_required=1,
            semester="S1",
        )
        link_primary = CourseClassLink(class_group=self.class_group)
        link_primary.teacher_a = self.teacher
        link_secondary = CourseClassLink(class_group=second_group)
        link_secondary.teacher_a = self.teacher
        course.class_links.extend([link_primary, link_secondary])
        course.set_teacher_hours(self.teacher, course.total_required_hours)
        db.session.add(course)
        db.session.commit()

        first_session = Session(
            course=course,
            teacher=self.teacher,
            room=self.room,
            class_group=self.class_group,
            start_time=datetime(2025, 9, 8, 8, 0, 0),
            end_time=datetime(2025, 9, 8, 9, 0, 0),
        )
        second_session = Session(
            course=course,
            teacher=self.teacher,
            room=self.room,
            class_group=self.class_group,
            start_time=datetime(2025, 9, 8, 10, 15, 0),
            end_time=datetime(2025, 9, 8, 11, 15, 0),
        )
        for session in (first_session, second_session):
            session.attendees = [self.class_group, second_group]
            db.session.add(session)
        db.session.commit()

        created = generate_schedule(
            course,
            window_start=date(2025, 9, 8),
            window_end=date(2025, 9, 12),
        )

        self.assertEqual(created, [])
        db.session.flush()
        log = course.latest_generation_log
        self.assertIsNotNone(log)
        self.assertEqual(log.status, "warning")


if __name__ == "__main__":
    unittest.main()
