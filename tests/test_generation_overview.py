import unittest
import uuid
from datetime import datetime, timedelta

from app import create_app, db
from app.models import (
    ClassGroup,
    Course,
    CourseClassLink,
    Room,
    Session,
    Teacher,
)
from config import TestConfig


class DatabaseTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.app = create_app(TestConfig)
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        db.session.remove()
        db.drop_all()
        self.app_context.pop()


class GenerationOverviewSummaryTestCase(DatabaseTestCase):
    def _create_course(
        self,
        *,
        suffix: str,
        sessions_required: int,
        session_length_hours: int = 2,
    ) -> tuple[Course, ClassGroup]:
        course = Course(
            name=f"TD - Analyse-{suffix} - S1",
            course_type="TD",
            semester="S1",
            session_length_hours=session_length_hours,
            sessions_required=sessions_required,
        )
        class_group = ClassGroup(name=f"INFO-{suffix}", size=24)
        link = CourseClassLink(class_group=class_group, group_count=1)
        course.class_links.append(link)
        db.session.add_all([course, class_group])
        db.session.commit()
        return course, class_group

    def _create_session(self, course: Course, class_group: ClassGroup) -> None:
        teacher = Teacher(name=f"Prof-{uuid.uuid4().hex[:8]}")
        room = Room(name=f"Salle-{uuid.uuid4().hex[:8]}", capacity=30)
        start = datetime(2025, 1, 6, 8, 0)
        end = start + timedelta(hours=course.session_length_hours)
        session = Session(
            course=course,
            teacher=teacher,
            room=room,
            class_group=class_group,
            start_time=start,
            end_time=end,
        )
        db.session.add_all([teacher, room, session])
        db.session.commit()

    def test_summary_cards_ignore_filters(self) -> None:
        course_a, class_a = self._create_course(
            suffix="A", sessions_required=1, session_length_hours=2
        )
        self._create_session(course_a, class_a)

        course_b, class_b = self._create_course(
            suffix="B", sessions_required=2, session_length_hours=2
        )

        prefix = self.app.config.get("URL_PREFIX", "")
        base_url = f"{prefix}/generation" if prefix else "/generation"
        response = self.client.get(f"{base_url}?class_id={class_b.id}")
        self.assertEqual(response.status_code, 200)
        compact_html = " ".join(response.get_data(as_text=True).split())

        self.assertIn(
            '<div class="generation-stat-value">2</div> '
            '<div class="generation-stat-label">Cours</div>',
            compact_html,
        )
        self.assertIn(
            '<div class="generation-stat-value">1</div> '
            '<div class="generation-stat-label">Cours planifiés</div>',
            compact_html,
        )
        self.assertIn(
            '<div class="generation-stat-value">2</div> '
            '<div class="generation-stat-label">Heures planifiées</div>',
            compact_html,
        )
        self.assertIn(
            '<div class="generation-stat-value">4</div> '
            '<div class="generation-stat-label">Heures restantes</div>',
            compact_html,
        )


if __name__ == "__main__":
    unittest.main()
