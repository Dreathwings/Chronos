import unittest
from datetime import datetime, timedelta

from app import create_app, db
from app.models import (
    ClassGroup,
    Course,
    CourseClassLink,
    CourseName,
    CourseTeacherAssignment,
    Room,
    Session,
    Teacher,
)
from app.routes import _validate_session_constraints
from app.scheduler import find_available_teacher
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


class CourseTeacherAssignmentTest(DatabaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.teacher = Teacher(name="Alice")
        self.course_name = CourseName(name="Programmation")
        self.class_group = ClassGroup(name="INFO1", size=30)
        self.room = Room(name="B101", capacity=40)
        db.session.add_all([self.teacher, self.course_name, self.class_group, self.room])
        db.session.commit()

    def _create_course(self, course_type: str = "TD") -> Course:
        course = Course(
            name=Course.compose_name(course_type, self.course_name.name, "S1"),
            course_type=course_type,
            session_length_hours=2,
            sessions_required=2,
            semester="S1",
            configured_name=self.course_name,
        )
        link = CourseClassLink(class_group=self.class_group)
        course.class_links.append(link)
        db.session.add(course)
        db.session.commit()
        return course

    def test_remaining_hours_tracks_scheduled_sessions(self) -> None:
        course = self._create_course()
        assignment = CourseTeacherAssignment(teacher=self.teacher, planned_hours=6)
        course.teacher_assignments.append(assignment)
        db.session.commit()

        # No sessions yet, remaining equals planned hours.
        self.assertEqual(course.remaining_hours_for_teacher(self.teacher), 6)

        session = Session(
            course=course,
            teacher=self.teacher,
            room=self.room,
            class_group=self.class_group,
            start_time=datetime(2024, 1, 8, 8, 0, 0),
            end_time=datetime(2024, 1, 8, 10, 0, 0),
        )
        session.attendees = [self.class_group]
        db.session.add(session)
        db.session.commit()

        self.assertEqual(course.remaining_hours_for_teacher(self.teacher), 4)

    def test_find_available_teacher_respects_planned_hours(self) -> None:
        course = self._create_course()
        CourseTeacherAssignment(course=course, teacher=self.teacher, planned_hours=2)
        db.session.commit()

        start_dt = datetime(2024, 1, 9, 8, 0, 0)
        end_dt = start_dt + timedelta(hours=2)

        teacher = find_available_teacher(
            course,
            start_dt,
            end_dt,
            link=course.class_links[0],
            target_class_ids={self.class_group.id},
        )
        self.assertIsNotNone(teacher)

        # Schedule a session consuming the planned hours.
        session = Session(
            course=course,
            teacher=self.teacher,
            room=self.room,
            class_group=self.class_group,
            start_time=start_dt,
            end_time=end_dt,
        )
        session.attendees = [self.class_group]
        db.session.add(session)
        db.session.commit()

        next_start = datetime(2024, 1, 16, 8, 0, 0)
        next_end = next_start + timedelta(hours=2)
        teacher_after_limit = find_available_teacher(
            course,
            next_start,
            next_end,
            link=course.class_links[0],
            target_class_ids={self.class_group.id},
        )
        self.assertIsNone(teacher_after_limit)

    def test_session_edit_validation(self) -> None:
        course = self._create_course()
        CourseTeacherAssignment(course=course, teacher=self.teacher, planned_hours=4)
        db.session.commit()

        session = Session(
            course=course,
            teacher=self.teacher,
            room=self.room,
            class_group=self.class_group,
            start_time=datetime(2024, 1, 15, 8, 0, 0),
            end_time=datetime(2024, 1, 15, 10, 0, 0),
        )
        session.attendees = [self.class_group]
        db.session.add(session)
        db.session.commit()

        error_message = _validate_session_constraints(
            course,
            self.teacher,
            self.room,
            [self.class_group],
            datetime(2024, 1, 22, 10, 0, 0),
            datetime(2024, 1, 22, 12, 0, 0),
            ignore_session_id=session.id,
            class_group_labels={self.class_group.id: None},
        )

        self.assertIsNone(error_message)


if __name__ == "__main__":
    unittest.main()
