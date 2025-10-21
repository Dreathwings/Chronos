import unittest
from datetime import datetime, timedelta

from app import create_app, db
from app.models import (
    ClassGroup,
    Course,
    CourseClassLink,
    CourseName,
    Room,
    Session,
    Teacher,
)
from app.scheduler import respects_weekly_chronology
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


class WeeklyChronologyRuleTestCase(DatabaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.base_name = CourseName(name="Analyse")
        self.class_group = ClassGroup(name="INFO1", size=24)
        self.teacher = Teacher(name="Alice")
        self.room = Room(name="B101", capacity=30)
        db.session.add_all([self.base_name, self.class_group, self.teacher, self.room])
        db.session.commit()

    def _create_course(
        self,
        course_type: str,
        *,
        use_configured: bool = True,
        group_count: int = 1,
    ) -> Course:
        course = Course(
            name=Course.compose_name(course_type, self.base_name.name, "S1"),
            course_type=course_type,
            session_length_hours=2,
            sessions_required=1,
            semester="S1",
        )
        if use_configured:
            course.configured_name = self.base_name
        link = CourseClassLink(class_group=self.class_group, group_count=group_count)
        course.class_links.append(link)
        db.session.add(course)
        db.session.commit()
        return course

    def _create_session(
        self, course: Course, start: datetime, *, subgroup_label: str | None = None
    ) -> Session:
        session = Session(
            course=course,
            class_group=self.class_group,
            teacher=self.teacher,
            room=self.room,
            start_time=start,
            end_time=start + timedelta(hours=course.session_length_hours),
            subgroup_label=subgroup_label,
        )
        session.attendees = [self.class_group]
        db.session.add(session)
        db.session.commit()
        return session

    def test_chronology_ignores_sessions_outside_target_week(self) -> None:
        course_cm = self._create_course("CM")
        course_td = self._create_course("TD")
        self._create_session(course_cm, datetime(2024, 1, 15, 8, 0, 0))

        allowed = respects_weekly_chronology(
            course_td,
            self.class_group,
            datetime(2024, 1, 8, 8, 0, 0),
        )

        self.assertTrue(allowed)

    def test_chronology_blocks_out_of_order_within_same_week(self) -> None:
        course_cm = self._create_course("CM")
        course_td = self._create_course("TD")
        self._create_session(course_cm, datetime(2024, 1, 10, 8, 0, 0))

        allowed = respects_weekly_chronology(
            course_td,
            self.class_group,
            datetime(2024, 1, 8, 8, 0, 0),
        )

        self.assertFalse(allowed)

    def test_chronology_blocks_out_of_order_within_same_day(self) -> None:
        course_cm = self._create_course("CM")
        course_td = self._create_course("TD")
        self._create_session(course_cm, datetime(2024, 1, 8, 14, 0, 0))

        allowed = respects_weekly_chronology(
            course_td,
            self.class_group,
            datetime(2024, 1, 8, 8, 0, 0),
        )

        self.assertFalse(allowed)

    def test_chronology_allows_progressive_order_same_day(self) -> None:
        course_cm = self._create_course("CM")
        course_td = self._create_course("TD")
        self._create_session(course_cm, datetime(2024, 1, 8, 8, 0, 0))

        allowed = respects_weekly_chronology(
            course_td,
            self.class_group,
            datetime(2024, 1, 8, 14, 0, 0),
        )

        self.assertTrue(allowed)

    def test_chronology_blocks_when_courses_share_only_display_name(self) -> None:
        course_cm = self._create_course("CM", use_configured=False)
        course_td = self._create_course("TD", use_configured=False)
        self._create_session(course_cm, datetime(2024, 1, 10, 8, 0, 0))

        allowed = respects_weekly_chronology(
            course_td,
            self.class_group,
            datetime(2024, 1, 8, 8, 0, 0),
        )

        self.assertFalse(allowed)

    def test_chronology_blocks_across_subgroups(self) -> None:
        course_td = self._create_course("TD", group_count=2)
        course_tp = self._create_course("TP", group_count=2)
        self._create_session(
            course_td,
            datetime(2024, 1, 10, 8, 0, 0),
            subgroup_label="A",
        )

        allowed = respects_weekly_chronology(
            course_tp,
            self.class_group,
            datetime(2024, 1, 8, 8, 0, 0),
            subgroup_label="B",
        )

        self.assertFalse(allowed)


if __name__ == "__main__":
    unittest.main()
