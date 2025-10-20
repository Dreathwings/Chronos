import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

from app import (create_app, db, _realign_tp_session_teachers,
    _ensure_session_subgroup_uniqueness_constraint,
)
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


class TeacherAssignmentTestCase(DatabaseTestCase):
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

    def test_session_event_lists_only_relevant_subgroup_teacher(self) -> None:
        course, link, class_group = self._create_tp_course()
        teacher_a = Teacher(name="Alice")
        teacher_b = Teacher(name="Bruno")
        room = Room(name="B202", capacity=24)
        db.session.add_all([teacher_a, teacher_b, room])
        db.session.commit()

        link.teacher_a = teacher_a
        link.teacher_b = teacher_b
        db.session.commit()

        start = datetime(2024, 1, 10, 8, 0, 0)
        end = datetime(2024, 1, 10, 10, 0, 0)
        session = Session(
            course=course,
            teacher=teacher_b,
            room=room,
            class_group=class_group,
            subgroup_label="B",
            start_time=start,
            end_time=end,
        )
        session.attendees = [class_group]
        db.session.add(session)
        db.session.commit()

        event = session.as_event()
        teachers = event["extendedProps"]["teachers"]
        self.assertEqual([entry["id"] for entry in teachers], [teacher_b.id])
        self.assertEqual(event["extendedProps"]["teacher"], teacher_b.name)


class SubgroupParallelismTestCase(DatabaseTestCase):
    def test_uniqueness_constraint_upgrade_emits_mysql_statements(self) -> None:
        engine = db.engine
        connection = MagicMock()
        begin_cm = MagicMock()
        begin_cm.__enter__.return_value = connection
        begin_cm.__exit__.return_value = False

        inspector = MagicMock()
        inspector.get_table_names.return_value = ["session"]
        inspector.get_unique_constraints.return_value = [
            {"name": "uq_class_start_time", "column_names": ["class_group_id", "start_time"]}
        ]
        inspector.get_indexes.return_value = []

        original_name = engine.dialect.name
        with patch("app.inspect", return_value=inspector):
            with patch.object(engine, "begin", return_value=begin_cm):
                engine.dialect.name = "mysql"
                try:
                    _ensure_session_subgroup_uniqueness_constraint()
                finally:
                    engine.dialect.name = original_name

        executed = [call.args[0].text for call in connection.execute.call_args_list]
        self.assertIn("ALTER TABLE session DROP INDEX uq_class_start_time", executed)
        self.assertIn(
            "ALTER TABLE session ADD CONSTRAINT uq_class_start_time UNIQUE (class_group_id, subgroup_label, start_time)",
            executed,
        )

    def test_uniqueness_constraint_upgrade_drops_unique_index(self) -> None:
        engine = db.engine
        connection = MagicMock()
        begin_cm = MagicMock()
        begin_cm.__enter__.return_value = connection
        begin_cm.__exit__.return_value = False

        inspector = MagicMock()
        inspector.get_table_names.return_value = ["session"]
        inspector.get_unique_constraints.return_value = []
        inspector.get_indexes.return_value = [
            {
                "name": "uq_class_start_time",
                "column_names": ["class_group_id", "start_time"],
                "unique": True,
            }
        ]

        original_name = engine.dialect.name
        with patch("app.inspect", return_value=inspector):
            with patch.object(engine, "begin", return_value=begin_cm):
                engine.dialect.name = "mysql"
                try:
                    _ensure_session_subgroup_uniqueness_constraint()
                finally:
                    engine.dialect.name = original_name

        executed = [call.args[0].text for call in connection.execute.call_args_list]
        self.assertIn("ALTER TABLE session DROP INDEX uq_class_start_time", executed)
        self.assertIn(
            "ALTER TABLE session ADD CONSTRAINT uq_class_start_time UNIQUE (class_group_id, subgroup_label, start_time)",
            executed,
        )

    def test_parallel_tp_sessions_for_distinct_subgroups(self) -> None:
        class_group = ClassGroup(name="INFO1", size=24)
        base_name_a = CourseName(name="Électronique")
        base_name_b = CourseName(name="Automatique")
        course_a = Course(
            name=Course.compose_name("TP", base_name_a.name, "S1"),
            course_type="TP",
            session_length_hours=2,
            sessions_required=2,
            semester="S1",
            configured_name=base_name_a,
        )
        course_b = Course(
            name=Course.compose_name("TP", base_name_b.name, "S1"),
            course_type="TP",
            session_length_hours=2,
            sessions_required=2,
            semester="S1",
            configured_name=base_name_b,
        )
        link_a = CourseClassLink(class_group=class_group, group_count=2)
        link_b = CourseClassLink(class_group=class_group, group_count=2)
        course_a.class_links.append(link_a)
        course_b.class_links.append(link_b)

        teacher_a = Teacher(name="Alice")
        teacher_b = Teacher(name="Bruno")
        room_a = Room(name="Labo A", capacity=24)
        room_b = Room(name="Labo B", capacity=24)

        db.session.add_all(
            [
                class_group,
                base_name_a,
                base_name_b,
                course_a,
                course_b,
                teacher_a,
                teacher_b,
                room_a,
                room_b,
            ]
        )
        db.session.commit()

        start = datetime(2024, 1, 8, 8, 0, 0)
        end = datetime(2024, 1, 8, 10, 0, 0)

        session_a = Session(
            course=course_a,
            teacher=teacher_a,
            room=room_a,
            class_group=class_group,
            subgroup_label="A",
            start_time=start,
            end_time=end,
        )
        session_a.attendees = [class_group]
        db.session.add(session_a)
        db.session.commit()

        self.assertFalse(class_group.is_available_during(start, end, subgroup_label="A"))
        self.assertTrue(class_group.is_available_during(start, end, subgroup_label="B"))
        self.assertFalse(class_group.is_available_during(start, end))

        session_b = Session(
            course=course_b,
            teacher=teacher_b,
            room=room_b,
            class_group=class_group,
            subgroup_label="B",
            start_time=start,
            end_time=end,
        )
        session_b.attendees = [class_group]
        db.session.add(session_b)
        db.session.commit()

        self.assertEqual(Session.query.count(), 2)
        self.assertFalse(class_group.is_available_during(start, end, subgroup_label="B"))
        self.assertFalse(class_group.is_available_during(start, end))


if __name__ == "__main__":
    unittest.main()
