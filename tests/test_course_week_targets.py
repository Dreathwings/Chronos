import math
import unittest
import uuid
from collections import OrderedDict
from datetime import date

from app import create_app, db
from app.models import (
    ClassGroup,
    Course,
    CourseAllowedWeek,
    CourseClassLink,
    CourseName,
)
from app.routes import _sync_course_allowed_weeks
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


class CourseWeekTargetTestCase(DatabaseTestCase):
    def _build_course(
        self,
        *,
        course_type: str = "TD",
        class_count: int = 2,
        group_count: int = 1,
        sessions_required: int = 3,
    ) -> Course:
        suffix = uuid.uuid4().hex
        base_name = CourseName(name=f"Analyse-{suffix}")
        course = Course(
            name=Course.compose_name(course_type, base_name.name, "S1"),
            course_type=course_type,
            session_length_hours=2,
            sessions_required=sessions_required,
            semester="S1",
            configured_name=base_name,
        )
        db.session.add(base_name)
        for index in range(class_count):
            class_group = ClassGroup(name=f"INFO{index + 1}-{suffix}", size=24)
            link = CourseClassLink(class_group=class_group, group_count=group_count)
            course.class_links.append(link)
            db.session.add(class_group)
        db.session.add(course)
        db.session.commit()
        return course

    def test_session_group_multiplier_counts_classes_and_groups(self) -> None:
        course_td = self._build_course(course_type="TD", class_count=3)
        self.assertEqual(course_td.session_group_multiplier, 3)

        course_tp = self._build_course(course_type="TP", class_count=1, group_count=2)
        self.assertEqual(course_tp.session_group_multiplier, 2)

        course_cm = self._build_course(course_type="CM", class_count=4)
        self.assertEqual(course_cm.session_group_multiplier, 1)

    def test_default_week_target_uses_total_sessions(self) -> None:
        course = self._build_course(class_count=2, sessions_required=3)
        target = course._default_weekly_target(3)
        self.assertEqual(target, 2)

    def test_sync_allowed_weeks_updates_sessions_per_class(self) -> None:
        course = self._build_course(class_count=2, sessions_required=2)
        first_week = date(2024, 1, 8)
        second_week = date(2024, 1, 15)
        targets = OrderedDict(
            (
                (first_week, 4),
                (second_week, 2),
            )
        )

        synchronised = _sync_course_allowed_weeks(course, targets)
        total_sessions = sum(synchronised.values())
        multiplier = course.session_group_multiplier
        per_class_target = max(int(math.ceil(total_sessions / multiplier)), 1)
        course.sessions_required = per_class_target
        db.session.commit()

        self.assertEqual(course.sessions_required, 3)

        total_hours = course.total_required_hours
        self.assertEqual(total_hours, (4 + 2) * course.session_length_hours)

    def test_total_required_hours_falls_back_to_base_when_targets_empty(self) -> None:
        course = self._build_course(class_count=2, sessions_required=2)
        self.assertEqual(
            course.total_required_hours,
            course.session_length_hours * course.session_group_multiplier * course.sessions_required,
        )

        week_start = date(2024, 1, 8)
        empty_target = CourseAllowedWeek(week_start=week_start, sessions_target=None)
        course.allowed_weeks.append(empty_target)
        db.session.commit()

        expected_total = course._default_weekly_target(1)
        self.assertEqual(
            course.total_required_hours,
            expected_total * course.session_length_hours,
        )


if __name__ == "__main__":
    unittest.main()
