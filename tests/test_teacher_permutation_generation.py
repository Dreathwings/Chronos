import json
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

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


class TeacherPermutationGenerationTestCase(DatabaseTestCase):
    def _setup_course(self) -> tuple[Course, list[CourseClassLink], list[Teacher], Room]:
        base_name = CourseName(name="Physique")
        course = Course(
            name=Course.compose_name("TD", base_name.name, "S1"),
            course_type="TD",
            session_length_hours=2,
            sessions_required=2,
            semester="S1",
            configured_name=base_name,
        )
        room = Room(name="C201", capacity=30)
        teachers = [Teacher(name="Alice"), Teacher(name="Bob")]
        groups = [ClassGroup(name="G1", size=24), ClassGroup(name="G2", size=24)]
        db.session.add_all([base_name, course, room, *teachers, *groups])
        db.session.flush()

        links: list[CourseClassLink] = []
        for group, teacher in zip(groups, teachers):
            link = CourseClassLink(class_group=group)
            link.teacher_a = teacher
            course.class_links.append(link)
            links.append(link)

        course.teachers.extend(teachers)
        db.session.commit()
        return course, links, teachers, room

    def test_permutation_enables_generation(self) -> None:
        course, links, teachers, room = self._setup_course()
        desired_mapping = {
            link.class_group.name: teachers[1 - idx]
            for idx, link in enumerate(sorted(links, key=lambda l: l.class_group.name))
        }

        def fake_attempt(*args, **kwargs):
            course_arg: Course = args[0]
            ordered_links = sorted(
                course_arg.class_links, key=lambda link: link.class_group.name
            )
            current = {
                link.class_group.name: link.teacher_a for link in ordered_links
            }
            if all(current[name] is teacher for name, teacher in desired_mapping.items()):
                sessions: list[Session] = []
                base_start = datetime(2024, 1, 8, 8, 0)
                for index, link in enumerate(ordered_links):
                    start = base_start + timedelta(days=index)
                    end = start + timedelta(hours=course_arg.session_length_hours)
                    session = Session(
                        course=course_arg,
                        teacher=current[link.class_group.name],
                        room=room,
                        class_group=link.class_group,
                        start_time=start,
                        end_time=end,
                    )
                    session.attendees = [link.class_group]
                    db.session.add(session)
                    db.session.flush()
                    sessions.append(session)
                return sessions
            return []

        with patch("app.scheduler._generate_schedule_attempt", side_effect=fake_attempt):
            created = generate_schedule(course)

        self.assertEqual(len(created), 2)
        ordered_links = sorted(links, key=lambda link: link.class_group.name)
        self.assertIs(ordered_links[0].teacher_a, desired_mapping[ordered_links[0].class_group.name])
        self.assertIs(ordered_links[1].teacher_a, desired_mapping[ordered_links[1].class_group.name])
        stored_sessions = Session.query.filter_by(course_id=course.id).all()
        self.assertEqual(len(stored_sessions), 2)

        refreshed = db.session.get(Course, course.id)
        latest_log = refreshed.latest_generation_log
        self.assertIsNotNone(latest_log)
        assert latest_log is not None
        self.assertEqual(latest_log.status, "warning")
        self.assertIn("Permutation automatique des enseignants", latest_log.summary)
        log_entries = json.loads(latest_log.messages or "[]")
        teacher_entries = [
            entry
            for entry in log_entries
            if isinstance(entry, dict) and entry.get("code") == "teacher-permutation"
        ]
        self.assertTrue(teacher_entries)
        self.assertTrue(
            any("G1" in entry.get("message", "") or "G2" in entry.get("message", "") for entry in teacher_entries)
        )

    def test_permutation_failure_restores_state(self) -> None:
        course, links, teachers, room = self._setup_course()
        # Seed an existing session to ensure it survives unsuccessful permutations
        existing_session = Session(
            course=course,
            teacher=teachers[0],
            room=room,
            class_group=links[0].class_group,
            start_time=datetime(2024, 1, 8, 8, 0),
            end_time=datetime(2024, 1, 8, 10, 0),
        )
        existing_session.attendees = [links[0].class_group]
        db.session.add(existing_session)
        db.session.commit()

        with patch(
            "app.scheduler._generate_schedule_attempt", return_value=[]
        ) as mocked_attempt:
            created = generate_schedule(course)

        self.assertEqual(created, [])
        mocked_attempt.assert_called()
        # Teacher assignments remain unchanged
        for idx, link in enumerate(links):
            self.assertIs(link.teacher_a, teachers[idx])
        # Original session restored
        stored_sessions = Session.query.filter_by(course_id=course.id).all()
        self.assertEqual(len(stored_sessions), 1)
        restored = stored_sessions[0]
        self.assertEqual(restored.start_time, existing_session.start_time)
        self.assertEqual(restored.end_time, existing_session.end_time)
        self.assertIs(restored.teacher, teachers[0])
        self.assertIs(restored.room, room)


if __name__ == "__main__":
    unittest.main()
