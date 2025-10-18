import unittest
from datetime import datetime

from app import create_app, db, _realign_tp_session_teachers
from config import TestConfig
from app.models import (
    ClassGroup,
    Course,
    CourseClassLink,
    CourseName,
    Room,
    Session,
    Teacher,
)


class TeacherAssignmentTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.app = create_app(TestConfig)
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

    def tearDown(self) -> None:
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def _create_tp_course(self) -> tuple[Course, CourseClassLink, ClassGroup]:
        base_name = CourseName(name="Programmation")
        course = Course(
            name=Course.compose_name("TP", base_name.name, "S1"),
            course_type="TP",
            session_length_hours=2,
            sessions_required=2,
            semester="S1",
            configured_name=base_name,
        )
        class_group = ClassGroup(name="INFO1", size=24)
        link = CourseClassLink(class_group=class_group, group_count=2)
        course.class_links.append(link)
        db.session.add_all([course, class_group, base_name])
        db.session.commit()
        return course, link, class_group

    def test_preferred_teachers_follow_subgroup_assignment(self) -> None:
        course, link, _ = self._create_tp_course()
        teacher_a = Teacher(name="Alice")
        teacher_b = Teacher(name="Bruno")
        db.session.add_all([teacher_a, teacher_b])
        db.session.commit()

        link.teacher_a = teacher_a
        link.teacher_b = teacher_b
        db.session.commit()

        self.assertEqual(link.teacher_for_label("A"), teacher_a)
        self.assertEqual(link.teacher_for_label("B"), teacher_b)
        self.assertEqual([t.id for t in link.preferred_teachers("A")], [teacher_a.id])
        self.assertEqual([t.id for t in link.preferred_teachers("B")], [teacher_b.id])

        # If a subgroup lacks a dedicated teacher we gracefully fall back to the available one.
        link.teacher_b = None
        db.session.commit()
        self.assertEqual([t.id for t in link.preferred_teachers("B")], [teacher_a.id])

    def test_cleanup_command_realigns_existing_sessions(self) -> None:
        course, link, class_group = self._create_tp_course()
        teacher_a = Teacher(name="Alice")
        teacher_b = Teacher(name="Bruno")
        room = Room(name="B201", capacity=24)
        db.session.add_all([teacher_a, teacher_b, room])
        db.session.commit()

        link.teacher_a = teacher_a
        link.teacher_b = teacher_b
        db.session.commit()

        start = datetime(2024, 1, 8, 8, 0, 0)
        end = datetime(2024, 1, 8, 10, 0, 0)
        session = Session(
            course=course,
            teacher=teacher_a,
            room=room,
            class_group=class_group,
            subgroup_label="B",
            start_time=start,
            end_time=end,
        )
        session.attendees = [class_group]
        db.session.add(session)
        db.session.commit()

        runner = self.app.test_cli_runner()
        result = runner.invoke(args=["clean-session-teachers"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("1 séance(s) corrigée(s).", result.output)

        updated = db.session.get(Session, session.id)
        self.assertIsNotNone(updated)
        self.assertEqual(updated.teacher_id, teacher_b.id)

    def test_realign_helper_updates_sessions(self) -> None:
        course, link, class_group = self._create_tp_course()
        teacher_a = Teacher(name="Alice")
        teacher_b = Teacher(name="Bruno")
        room = Room(name="B201", capacity=24)
        db.session.add_all([teacher_a, teacher_b, room])
        db.session.commit()

        link.teacher_a = teacher_a
        link.teacher_b = teacher_b
        db.session.commit()

        start = datetime(2024, 1, 9, 8, 0, 0)
        end = datetime(2024, 1, 9, 10, 0, 0)
        session = Session(
            course=course,
            teacher=teacher_a,
            room=room,
            class_group=class_group,
            subgroup_label="B",
            start_time=start,
            end_time=end,
        )
        session.attendees = [class_group]
        db.session.add(session)
        db.session.commit()

        updated = _realign_tp_session_teachers()
        self.assertEqual(updated, 1)

        refreshed = db.session.get(Session, session.id)
        self.assertIsNotNone(refreshed)
        self.assertEqual(refreshed.teacher_id, teacher_b.id)


if __name__ == "__main__":
    unittest.main()
