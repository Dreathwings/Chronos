import unittest

from app import create_app, db
from app.generation import CourseScheduleState
from app.models import ClassGroup, Course, CourseClassLink, CourseName
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


class CourseScheduleStateWeeklyTargetTestCase(DatabaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.base_name = CourseName(name="Génie logiciel")
        db.session.add(self.base_name)
        db.session.commit()

    def _create_course(self, course_type: str, group_counts: list[int]) -> Course:
        course = Course(
            name=Course.compose_name(course_type, self.base_name.name, "S1"),
            course_type=course_type,
            session_length_hours=2,
            sessions_required=4,
            sessions_per_week=1,
            semester="S1",
            configured_name=self.base_name,
        )
        for index, group_count in enumerate(group_counts, start=1):
            class_group = ClassGroup(name=f"INFO{index}", size=28)
            link = CourseClassLink(class_group=class_group, group_count=group_count)
            course.class_links.append(link)
            db.session.add(class_group)
        db.session.add(course)
        db.session.commit()
        return course

    def test_tp_targets_hours_for_both_subgroups(self) -> None:
        course = self._create_course("TP", [2])
        state = CourseScheduleState(course)
        week_start, _ = state.allowed_spans[0]

        target = state.weekly_hours_target(week_start)

        self.assertEqual(target, 4)

    def test_cm_targets_single_block_even_with_multiple_classes(self) -> None:
        course = self._create_course("CM", [1, 1])
        state = CourseScheduleState(course)
        week_start, _ = state.allowed_spans[0]

        target = state.weekly_hours_target(week_start)

        self.assertEqual(target, 2)


if __name__ == "__main__":
    unittest.main()

