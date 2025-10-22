import unittest
from datetime import date, datetime, time, timedelta

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


class SaeSplitOptionTestCase(DatabaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.teacher_primary = Teacher(name="Alice")
        self.teacher_secondary = Teacher(name="Bruno")
        self.room = Room(name="Projet 1", capacity=40)
        self.class_group = ClassGroup(name="INFO SAE", size=28)
        db.session.add_all(
            [
                self.teacher_primary,
                self.teacher_secondary,
                self.room,
                self.class_group,
            ]
        )
        db.session.commit()

        for teacher in (self.teacher_primary, self.teacher_secondary):
            availability = TeacherAvailability(
                teacher=teacher,
                weekday=0,
                start_time=time(8, 0),
                end_time=time(18, 0),
            )
            db.session.add(availability)
        db.session.commit()

    def _create_course(self, *, consecutive: bool) -> Course:
        course = Course(
            name="SAE - Projet - S1",
            course_type="SAE",
            session_length_hours=4,
            sessions_required=1,
            semester="S1",
            sae_split_consecutive=consecutive,
        )
        link = CourseClassLink(class_group=self.class_group)
        link.teacher_a = self.teacher_primary
        link.teacher_b = self.teacher_secondary
        course.class_links.append(link)
        course.teachers.extend([self.teacher_primary, self.teacher_secondary])
        db.session.add(course)
        db.session.commit()
        return course

    def _add_blocking_sessions(self) -> None:
        blocker = Course(
            name="TD - Blocage - S1",
            course_type="TD",
            session_length_hours=2,
            sessions_required=1,
            semester="S1",
        )
        blocker_link = CourseClassLink(class_group=self.class_group)
        blocker_link.teacher_a = self.teacher_primary
        blocker.class_links.append(blocker_link)
        blocker.teachers.append(self.teacher_primary)
        db.session.add(blocker)
        db.session.commit()

        blocking_slots = [
            (datetime(2025, 9, 8, 10, 15, 0), datetime(2025, 9, 8, 12, 15, 0)),
            (datetime(2025, 9, 8, 15, 45, 0), datetime(2025, 9, 8, 16, 45, 0)),
        ]
        for start_dt, end_dt in blocking_slots:
            session = Session(
                course=blocker,
                teacher=self.teacher_primary,
                room=self.room,
                class_group=self.class_group,
                start_time=start_dt,
                end_time=end_dt,
            )
            session.attendees = [self.class_group]
            db.session.add(session)
        db.session.commit()

    def test_requires_consecutive_segments_by_default(self) -> None:
        course = self._create_course(consecutive=True)
        self._add_blocking_sessions()

        with self.assertRaises(ValueError):
            generate_schedule(
                course,
                window_start=date(2025, 9, 8),
                window_end=date(2025, 9, 8),
            )

    def test_allows_non_consecutive_segments_when_disabled(self) -> None:
        course = self._create_course(consecutive=False)
        self._add_blocking_sessions()

        created = generate_schedule(
            course,
            window_start=date(2025, 9, 8),
            window_end=date(2025, 9, 8),
        )

        self.assertEqual(len(created), 2)
        ordered = sorted(created, key=lambda session: session.start_time)
        morning, afternoon = ordered
        self.assertEqual(morning.start_time, datetime(2025, 9, 8, 8, 0, 0))
        self.assertEqual(morning.end_time, datetime(2025, 9, 8, 10, 0, 0))
        self.assertEqual(afternoon.start_time, datetime(2025, 9, 8, 13, 30, 0))
        self.assertEqual(afternoon.end_time, datetime(2025, 9, 8, 15, 30, 0))
        self.assertGreater(
            afternoon.start_time - morning.end_time,
            timedelta(minutes=60),
        )
