import unittest
from collections import Counter
from datetime import date, datetime, time, timedelta
from itertools import combinations
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
    CourseScheduleLog,
    Equipment,
    Room,
    Session,
    Teacher,
    TeacherAvailability,
    best_teacher_duos,
    recommend_teacher_duos_for_classes,
)
from sqlalchemy import text
from app.routes import _validate_session_constraints
from app.scheduler import (
    ScheduleReporter,
    generate_schedule,
    _relocate_sessions_for_groups,
    _class_hours_needed,
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

    def test_session_event_uses_course_color(self) -> None:
        course, link, class_group = self._create_tp_course()
        course.color = "#FF00FF"
        teacher = Teacher(name="Alice")
        room = Room(name="B203", capacity=24)
        db.session.add_all([teacher, room])
        db.session.commit()

        link.teacher_a = teacher
        db.session.commit()

        start = datetime(2024, 1, 11, 8, 0)
        end = datetime(2024, 1, 11, 10, 0)
        session = Session(
            course=course,
            teacher=teacher,
            room=room,
            class_group=class_group,
            start_time=start,
            end_time=end,
        )
        session.attendees = [class_group]
        db.session.add(session)
        db.session.commit()

        event = session.as_event()
        self.assertEqual(event["backgroundColor"], "#FF00FF")
        self.assertEqual(event["borderColor"], "#FF00FF")

    def test_best_teacher_duos_prefers_shared_availability(self) -> None:
        teacher_a = Teacher(name="Alice")
        teacher_b = Teacher(name="Bruno")
        teacher_c = Teacher(name="Chloé")
        db.session.add_all([teacher_a, teacher_b, teacher_c])
        db.session.commit()

        availabilities = [
            TeacherAvailability(
                teacher=teacher_a,
                weekday=0,
                start_time=time(8, 0),
                end_time=time(12, 0),
            ),
            TeacherAvailability(
                teacher=teacher_a,
                weekday=1,
                start_time=time(8, 0),
                end_time=time(12, 0),
            ),
            TeacherAvailability(
                teacher=teacher_b,
                weekday=0,
                start_time=time(9, 0),
                end_time=time(12, 0),
            ),
            TeacherAvailability(
                teacher=teacher_b,
                weekday=1,
                start_time=time(13, 0),
                end_time=time(17, 0),
            ),
            TeacherAvailability(
                teacher=teacher_c,
                weekday=0,
                start_time=time(10, 0),
                end_time=time(12, 0),
            ),
            TeacherAvailability(
                teacher=teacher_c,
                weekday=1,
                start_time=time(8, 0),
                end_time=time(12, 0),
            ),
        ]
        db.session.add_all(availabilities)
        db.session.commit()

        pairs = best_teacher_duos([teacher_a, teacher_b, teacher_c], limit=2)

        self.assertEqual(len(pairs), 2)
        self.assertEqual((pairs[0][0].id, pairs[0][1].id), (teacher_a.id, teacher_c.id))
        self.assertAlmostEqual(pairs[0][2], 6.0)
        self.assertEqual({pairs[1][0].id, pairs[1][1].id}, {teacher_a.id, teacher_b.id})
        self.assertAlmostEqual(pairs[1][2], 3.0)

    def test_best_teacher_duos_returns_zero_overlap_when_needed(self) -> None:
        teacher_a = Teacher(name="Alice")
        teacher_b = Teacher(name="Bruno")
        db.session.add_all([teacher_a, teacher_b])
        db.session.commit()

        availabilities = [
            TeacherAvailability(
                teacher=teacher_a,
                weekday=0,
                start_time=time(8, 0),
                end_time=time(10, 0),
            ),
            TeacherAvailability(
                teacher=teacher_b,
                weekday=0,
                start_time=time(10, 0),
                end_time=time(12, 0),
            ),
        ]
        db.session.add_all(availabilities)
        db.session.commit()

        pairs = best_teacher_duos([teacher_a, teacher_b], limit=5)

        self.assertEqual(len(pairs), 1)
        self.assertEqual({pairs[0][0].id, pairs[0][1].id}, {teacher_a.id, teacher_b.id})
        self.assertAlmostEqual(pairs[0][2], 0.0)

    def test_recommended_duos_avoid_teacher_duplicates(self) -> None:
        course, link_a, _ = self._create_tp_course()
        class_group_b = ClassGroup(name="INFO2", size=24)
        link_b = CourseClassLink(class_group=class_group_b, group_count=2)
        course.class_links.append(link_b)
        db.session.add(class_group_b)
        db.session.commit()

        teacher_a = Teacher(name="Alice")
        teacher_b = Teacher(name="Bruno")
        teacher_c = Teacher(name="Chloé")
        teacher_d = Teacher(name="David")
        db.session.add_all([teacher_a, teacher_b, teacher_c, teacher_d])
        db.session.commit()

        availabilities = [
            TeacherAvailability(
                teacher=teacher_a,
                weekday=0,
                start_time=time(8, 0),
                end_time=time(12, 0),
            ),
            TeacherAvailability(
                teacher=teacher_b,
                weekday=0,
                start_time=time(8, 0),
                end_time=time(12, 0),
            ),
            TeacherAvailability(
                teacher=teacher_c,
                weekday=0,
                start_time=time(13, 0),
                end_time=time(17, 0),
            ),
            TeacherAvailability(
                teacher=teacher_d,
                weekday=0,
                start_time=time(13, 0),
                end_time=time(17, 0),
            ),
        ]
        db.session.add_all(availabilities)
        db.session.commit()

        duos = recommend_teacher_duos_for_classes(
            course.class_links,
            [teacher_a, teacher_b, teacher_c, teacher_d],
        )

        self.assertEqual(
            set(duos.keys()),
            {link_a.class_group_id, link_b.class_group_id},
        )
        used_teacher_ids = set()
        for teacher_a_obj, teacher_b_obj, _ in duos.values():
            used_teacher_ids.add(teacher_a_obj.id)
            used_teacher_ids.add(teacher_b_obj.id)
        self.assertEqual(used_teacher_ids, {teacher_a.id, teacher_b.id, teacher_c.id, teacher_d.id})

    def test_recommended_duos_skip_when_not_enough_teachers(self) -> None:
        course, link_a, _ = self._create_tp_course()
        class_group_b = ClassGroup(name="INFO3", size=24)
        link_b = CourseClassLink(class_group=class_group_b, group_count=2)
        course.class_links.append(link_b)
        db.session.add(class_group_b)
        db.session.commit()

        teacher_a = Teacher(name="Alice")
        teacher_b = Teacher(name="Bruno")
        teacher_c = Teacher(name="Chloé")
        db.session.add_all([teacher_a, teacher_b, teacher_c])
        db.session.commit()

        availabilities = [
            TeacherAvailability(
                teacher=teacher_a,
                weekday=0,
                start_time=time(8, 0),
                end_time=time(12, 0),
            ),
            TeacherAvailability(
                teacher=teacher_b,
                weekday=0,
                start_time=time(8, 0),
                end_time=time(12, 0),
            ),
            TeacherAvailability(
                teacher=teacher_c,
                weekday=0,
                start_time=time(8, 0),
                end_time=time(12, 0),
            ),
        ]
        db.session.add_all(availabilities)
        db.session.commit()

        duos = recommend_teacher_duos_for_classes(
            course.class_links,
            [teacher_a, teacher_b, teacher_c],
        )

        self.assertIn(link_a.class_group_id, duos)
        self.assertNotIn(link_b.class_group_id, duos)

    def test_recommended_duos_maximise_shared_availability(self) -> None:
        course, link_a, _ = self._create_tp_course()
        class_group_b = ClassGroup(name="INFO4", size=24)
        link_b = CourseClassLink(class_group=class_group_b, group_count=2)
        course.class_links.append(link_b)
        db.session.add(class_group_b)
        db.session.commit()

        teacher_a = Teacher(name="Alice")
        teacher_b = Teacher(name="Bruno")
        teacher_c = Teacher(name="Chloé")
        teacher_d = Teacher(name="David")
        db.session.add_all([teacher_a, teacher_b, teacher_c, teacher_d])
        db.session.commit()

        availabilities = [
            TeacherAvailability(
                teacher=teacher_a,
                weekday=0,
                start_time=time(8, 0),
                end_time=time(18, 0),
            ),
            TeacherAvailability(
                teacher=teacher_a,
                weekday=1,
                start_time=time(8, 0),
                end_time=time(17, 0),
            ),
            TeacherAvailability(
                teacher=teacher_b,
                weekday=0,
                start_time=time(8, 0),
                end_time=time(18, 0),
            ),
            TeacherAvailability(
                teacher=teacher_b,
                weekday=2,
                start_time=time(8, 0),
                end_time=time(17, 0),
            ),
            TeacherAvailability(
                teacher=teacher_c,
                weekday=2,
                start_time=time(8, 0),
                end_time=time(17, 0),
            ),
            TeacherAvailability(
                teacher=teacher_d,
                weekday=1,
                start_time=time(8, 0),
                end_time=time(17, 0),
            ),
        ]
        db.session.add_all(availabilities)
        db.session.commit()

        duos = recommend_teacher_duos_for_classes(
            course.class_links,
            [teacher_a, teacher_b, teacher_c, teacher_d],
        )

        self.assertEqual(
            set(duos.keys()),
            {link_a.class_group_id, link_b.class_group_id},
        )
        recommended_pairs = {
            frozenset((teacher_a_obj.id, teacher_b_obj.id))
            for teacher_a_obj, teacher_b_obj, _ in duos.values()
        }
        self.assertEqual(
            recommended_pairs,
            {
                frozenset((teacher_a.id, teacher_d.id)),
                frozenset((teacher_b.id, teacher_c.id)),
            },
        )

        pair_scores = {
            frozenset((first.id, second.id)): first.overlapping_available_hours(second)
            for first, second in combinations(
                [teacher_a, teacher_b, teacher_c, teacher_d],
                2,
            )
        }
        best_mean = float("-inf")
        for first_pair, second_pair in combinations(pair_scores.keys(), 2):
            if len(first_pair | second_pair) != 4:
                continue
            candidate_mean = (pair_scores[first_pair] + pair_scores[second_pair]) / 2
            if candidate_mean > best_mean:
                best_mean = candidate_mean

        recommended_mean = sum(overlap for _, _, overlap in duos.values()) / len(duos)
        self.assertAlmostEqual(recommended_mean, best_mean)


class DashboardActionsTestCase(DatabaseTestCase):
    def test_clear_all_sessions_removes_every_course_schedule(self) -> None:
        base_name_a = CourseName(name="Analyse")
        base_name_b = CourseName(name="Algèbre")

        course_a = Course(
            name=Course.compose_name("CM", base_name_a.name, "S1"),
            course_type="CM",
            session_length_hours=2,
            sessions_required=2,
            semester="S1",
            configured_name=base_name_a,
        )
        course_b = Course(
            name=Course.compose_name("TD", base_name_b.name, "S1"),
            course_type="TD",
            session_length_hours=2,
            sessions_required=2,
            semester="S1",
            configured_name=base_name_b,
        )

        class_a = ClassGroup(name="INFO2", size=24)
        class_b = ClassGroup(name="INFO3", size=24)
        link_a = CourseClassLink(class_group=class_a)
        link_b = CourseClassLink(class_group=class_b)
        course_a.class_links.append(link_a)
        course_b.class_links.append(link_b)

        teacher = Teacher(name="Claire")
        room = Room(name="B103", capacity=30)

        session_a = Session(
            course=course_a,
            teacher=teacher,
            room=room,
            class_group=class_a,
            start_time=datetime(2024, 1, 8, 8, 0, 0),
            end_time=datetime(2024, 1, 8, 10, 0, 0),
        )
        session_a.attendees = [class_a]

        session_b = Session(
            course=course_b,
            teacher=teacher,
            room=room,
            class_group=class_b,
            start_time=datetime(2024, 1, 9, 10, 0, 0),
            end_time=datetime(2024, 1, 9, 12, 0, 0),
        )
        session_b.attendees = [class_b]

        log_a = CourseScheduleLog(course=course_a, status="success", summary="OK")
        log_b = CourseScheduleLog(course=course_b, status="warning", summary="Warn")

        db.session.add_all(
            [
                base_name_a,
                base_name_b,
                course_a,
                course_b,
                class_a,
                class_b,
                teacher,
                room,
                session_a,
                session_b,
                log_a,
                log_b,
            ]
        )
        db.session.commit()

        self.assertEqual(Session.query.count(), 2)
        self.assertEqual(CourseScheduleLog.query.count(), 2)

        client = self.app.test_client()
        base_path = self.app.config.get("URL_PREFIX", "") or ""
        response = client.post(
            f"{base_path}/",
            data={"form": "clear-all-sessions"},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Session.query.count(), 0)
        self.assertEqual(CourseScheduleLog.query.count(), 0)


class SubgroupParallelismTestCase(DatabaseTestCase):
    def _mock_mysql_connections(
        self, stats_rows: list[dict[str, str]] | None = None
    ) -> tuple[MagicMock, MagicMock]:
        begin_connection = MagicMock()
        begin_cm = MagicMock()
        begin_cm.__enter__.return_value = begin_connection
        begin_cm.__exit__.return_value = False

        stats_rows = stats_rows or []
        stats_result = MagicMock()
        stats_result.mappings.return_value.all.return_value = stats_rows

        inspect_connection = MagicMock()
        inspect_connection.execute.return_value = stats_result

        connect_cm = MagicMock()
        connect_cm.__enter__.return_value = inspect_connection
        connect_cm.__exit__.return_value = False

        return begin_cm, connect_cm

    def test_uniqueness_constraint_upgrade_emits_mysql_statements(self) -> None:
        engine = db.engine
        begin_cm, connect_cm = self._mock_mysql_connections()

        inspector = MagicMock()
        inspector.get_table_names.return_value = ["session"]
        inspector.get_unique_constraints.return_value = [
            {"name": "uq_class_start_time", "column_names": ["class_group_id", "start_time"]}
        ]
        inspector.get_indexes.return_value = []

        original_name = engine.dialect.name
        with patch("app.inspect", return_value=inspector):
            with patch.object(engine, "begin", return_value=begin_cm):
                with patch.object(engine, "connect", return_value=connect_cm):
                    engine.dialect.name = "mysql"
                    begin_connection = begin_cm.__enter__.return_value
                    try:
                        _ensure_session_subgroup_uniqueness_constraint()
                    finally:
                        engine.dialect.name = original_name

        executed = [call.args[0].text for call in begin_connection.execute.call_args_list]
        self.assertIn(
            "ALTER TABLE session DROP INDEX `uq_class_start_time`, ADD UNIQUE INDEX `uq_class_start_time` (class_group_id, subgroup_label, start_time)",
            executed,
        )

    def test_uniqueness_constraint_upgrade_drops_unique_index(self) -> None:
        engine = db.engine
        begin_cm, connect_cm = self._mock_mysql_connections()

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
                with patch.object(engine, "connect", return_value=connect_cm):
                    engine.dialect.name = "mysql"
                    begin_connection = begin_cm.__enter__.return_value
                    try:
                        _ensure_session_subgroup_uniqueness_constraint()
                    finally:
                        engine.dialect.name = original_name

        executed = [call.args[0].text for call in begin_connection.execute.call_args_list]
        self.assertIn(
            "ALTER TABLE session DROP INDEX `uq_class_start_time`, ADD UNIQUE INDEX `uq_class_start_time` (class_group_id, subgroup_label, start_time)",
            executed,
        )

    def test_uniqueness_constraint_upgrade_drops_unknown_mysql_legacy(self) -> None:
        engine = db.engine
        begin_cm, connect_cm = self._mock_mysql_connections()

        inspector = MagicMock()
        inspector.get_table_names.return_value = ["session"]
        inspector.get_unique_constraints.return_value = [
            {
                "name": "legacy_unique",
                "column_names": ["class_group_id", "start_time"],
            }
        ]
        inspector.get_indexes.return_value = []

        original_name = engine.dialect.name
        with patch("app.inspect", return_value=inspector):
            with patch.object(engine, "begin", return_value=begin_cm):
                with patch.object(engine, "connect", return_value=connect_cm):
                    engine.dialect.name = "mysql"
                    begin_connection = begin_cm.__enter__.return_value
                    try:
                        _ensure_session_subgroup_uniqueness_constraint()
                    finally:
                        engine.dialect.name = original_name

        executed = [call.args[0].text for call in begin_connection.execute.call_args_list]
        self.assertIn("ALTER TABLE session DROP INDEX `legacy_unique`", executed)
        self.assertIn(
            "ALTER TABLE session ADD UNIQUE INDEX uq_class_start_time (class_group_id, subgroup_label, start_time)",
            executed,
        )

    def test_uniqueness_constraint_upgrade_noop_when_already_correct(self) -> None:
        engine = db.engine
        begin_cm, connect_cm = self._mock_mysql_connections()

        inspector = MagicMock()
        inspector.get_table_names.return_value = ["session"]
        inspector.get_unique_constraints.return_value = []
        inspector.get_indexes.return_value = [
            {
                "name": "uq_class_start_time",
                "column_names": [
                    "class_group_id",
                    "subgroup_label",
                    "start_time",
                ],
                "unique": True,
            }
        ]

        original_name = engine.dialect.name
        with patch("app.inspect", return_value=inspector):
            with patch.object(engine, "begin", return_value=begin_cm):
                with patch.object(engine, "connect", return_value=connect_cm):
                    engine.dialect.name = "mysql"
                    begin_connection = begin_cm.__enter__.return_value
                    try:
                        _ensure_session_subgroup_uniqueness_constraint()
                    finally:
                        engine.dialect.name = original_name

        self.assertFalse(begin_connection.execute.call_args_list)

    def test_uniqueness_constraint_upgrade_reads_mysql_information_schema(self) -> None:
        engine = db.engine
        stats_rows = [
            {"INDEX_NAME": "uq_class_start_time", "COLUMN_NAME": "class_group_id"},
            {"INDEX_NAME": "uq_class_start_time", "COLUMN_NAME": "start_time"},
        ]
        begin_cm, connect_cm = self._mock_mysql_connections(stats_rows=stats_rows)

        inspector = MagicMock()
        inspector.get_table_names.return_value = ["session"]
        inspector.get_unique_constraints.return_value = []
        inspector.get_indexes.return_value = []

        original_name = engine.dialect.name
        with patch("app.inspect", return_value=inspector):
            with patch.object(engine, "begin", return_value=begin_cm):
                with patch.object(engine, "connect", return_value=connect_cm):
                    engine.dialect.name = "mysql"
                    begin_connection = begin_cm.__enter__.return_value
                    try:
                        _ensure_session_subgroup_uniqueness_constraint()
                    finally:
                        engine.dialect.name = original_name

        executed = [call.args[0].text for call in begin_connection.execute.call_args_list]
        self.assertIn(
            "ALTER TABLE session DROP INDEX `uq_class_start_time`, ADD UNIQUE INDEX `uq_class_start_time` (class_group_id, subgroup_label, start_time)",
            executed,
        )

    def test_uniqueness_constraint_upgrade_rebuilds_sqlite_legacy(self) -> None:
        engine = db.engine
        with engine.begin() as connection:
            connection.execute(text("DROP TABLE IF EXISTS session"))
            connection.execute(
                text(
                    """
                    CREATE TABLE session (
                        id INTEGER PRIMARY KEY,
                        course_id INTEGER NOT NULL,
                        teacher_id INTEGER NOT NULL,
                        room_id INTEGER NOT NULL,
                        class_group_id INTEGER NOT NULL,
                        subgroup_label VARCHAR(1),
                        start_time DATETIME NOT NULL,
                        end_time DATETIME NOT NULL,
                        created_at DATETIME NOT NULL,
                        updated_at DATETIME NOT NULL,
                        UNIQUE(class_group_id, start_time),
                        UNIQUE(room_id, start_time)
                    )
                    """
                )
            )

        course, link, class_group = self._create_tp_course()
        teacher_a = Teacher(name="Alice")
        teacher_b = Teacher(name="Bruno")
        room_a = Room(name="A101", capacity=24)
        room_b = Room(name="B202", capacity=24)
        db.session.add_all([teacher_a, teacher_b, room_a, room_b])
        db.session.commit()

        link.teacher_a = teacher_a
        link.teacher_b = teacher_b
        db.session.commit()

        _ensure_session_subgroup_uniqueness_constraint()

        start = datetime(2025, 9, 17, 13, 30)
        end = datetime(2025, 9, 17, 15, 30)

        session_a = Session(
            course=course,
            teacher=teacher_a,
            room=room_a,
            class_group=class_group,
            subgroup_label="A",
            start_time=start,
            end_time=end,
        )
        session_b = Session(
            course=course,
            teacher=teacher_b,
            room=room_b,
            class_group=class_group,
            subgroup_label="B",
            start_time=start,
            end_time=end,
        )
        db.session.add_all([session_a, session_b])
        db.session.commit()

        with engine.connect() as connection:
            index_rows = connection.execute(
                text("PRAGMA index_list('session')")
            ).mappings().all()

        unique_indexes = [row for row in index_rows if row["unique"]]
        self.assertTrue(unique_indexes)

        def index_columns(name: str) -> list[str]:
            with engine.connect() as connection:
                return [
                    row["name"]
                    for row in connection.execute(
                        text(f"PRAGMA index_info('{name}')")
                    ).mappings()
                ]

        self.assertIn(
            ["class_group_id", "subgroup_label", "start_time"],
            [index_columns(row["name"]) for row in unique_indexes],
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


class ChronologyValidationTestCase(DatabaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.class_group = ClassGroup(name="INFO2", size=28)
        self.teacher = Teacher(name="Chloé")
        self.room = Room(name="C201", capacity=40)
        base_name = CourseName(name="Algorithmique")
        self.course_cm = Course(
            name=Course.compose_name("CM", base_name.name, "S1"),
            course_type="CM",
            session_length_hours=2,
            sessions_required=1,
            semester="S1",
            configured_name=base_name,
        )
        self.course_td = Course(
            name=Course.compose_name("TD", base_name.name, "S1"),
            course_type="TD",
            session_length_hours=2,
            sessions_required=1,
            semester="S1",
            configured_name=base_name,
        )
        self.course_tp = Course(
            name=Course.compose_name("TP", base_name.name, "S1"),
            course_type="TP",
            session_length_hours=2,
            sessions_required=1,
            semester="S1",
            configured_name=base_name,
        )
        self.course_eval = Course(
            name=Course.compose_name("Eval", base_name.name, "S1"),
            course_type="Eval",
            session_length_hours=2,
            sessions_required=1,
            semester="S1",
            configured_name=base_name,
        )
        for course in (
            self.course_cm,
            self.course_td,
            self.course_tp,
            self.course_eval,
        ):
            course.class_links.append(CourseClassLink(class_group=self.class_group))

        db.session.add_all(
            [
                self.class_group,
                self.teacher,
                self.room,
                base_name,
                self.course_cm,
                self.course_td,
                self.course_tp,
                self.course_eval,
            ]
        )
        db.session.commit()

        availabilities = [
            TeacherAvailability(
                teacher=self.teacher,
                weekday=weekday,
                start_time=time(8, 0),
                end_time=time(18, 0),
            )
            for weekday in range(5)
        ]
        db.session.add_all(availabilities)
        db.session.commit()

        db.session.commit()

    def test_validation_blocks_td_before_cm(self) -> None:
        cm_session = Session(
            course=self.course_cm,
            teacher=self.teacher,
            room=self.room,
            class_group=self.class_group,
            start_time=datetime(2024, 1, 11, 10, 15, 0),
            end_time=datetime(2024, 1, 11, 12, 15, 0),
        )
        cm_session.attendees = [self.class_group]
        db.session.add(cm_session)
        db.session.commit()

        start_dt = datetime(2024, 1, 9, 8, 0, 0)
        end_dt = datetime(2024, 1, 9, 10, 0, 0)
        error = _validate_session_constraints(
            self.course_td,
            self.teacher,
            self.room,
            [self.class_group],
            start_dt,
            end_dt,
        )
        self.assertIsNotNone(error)
        self.assertIn("chronologie", error)

    def test_validation_blocks_eval_before_tp(self) -> None:
        tp_session = Session(
            course=self.course_tp,
            teacher=self.teacher,
            room=self.room,
            class_group=self.class_group,
            start_time=datetime(2024, 1, 12, 10, 15, 0),
            end_time=datetime(2024, 1, 12, 12, 15, 0),
        )
        tp_session.attendees = [self.class_group]
        db.session.add(tp_session)
        db.session.commit()

        start_dt = datetime(2024, 1, 11, 8, 0, 0)
        end_dt = datetime(2024, 1, 11, 10, 0, 0)
        error = _validate_session_constraints(
            self.course_eval,
            self.teacher,
            self.room,
            [self.class_group],
            start_dt,
            end_dt,
        )
        self.assertIsNotNone(error)
        self.assertIn("chronologie", error)

    def test_validation_allows_ordered_sequence(self) -> None:
        start_dt = datetime(2024, 1, 12, 8, 0, 0)
        end_dt = datetime(2024, 1, 12, 10, 0, 0)
        error = _validate_session_constraints(
            self.course_td,
            self.teacher,
            self.room,
            [self.class_group],
            start_dt,
            end_dt,
        )
        self.assertIsNone(error)

    def test_validation_ignores_other_subject_sessions(self) -> None:
        other_name = CourseName(name="Mathématiques")
        other_cm = Course(
            name=Course.compose_name("CM", other_name.name, "S1"),
            course_type="CM",
            session_length_hours=2,
            sessions_required=1,
            semester="S1",
            configured_name=other_name,
        )
        other_cm.class_links.append(CourseClassLink(class_group=self.class_group))
        other_session = Session(
            course=other_cm,
            teacher=self.teacher,
            room=self.room,
            class_group=self.class_group,
            start_time=datetime(2024, 1, 12, 13, 30, 0),
            end_time=datetime(2024, 1, 12, 15, 30, 0),
        )
        other_session.attendees = [self.class_group]
        db.session.add_all([other_name, other_cm, other_session])
        db.session.commit()

        start_dt = datetime(2024, 1, 12, 8, 0, 0)
        end_dt = datetime(2024, 1, 12, 10, 0, 0)
        error = _validate_session_constraints(
            self.course_td,
            self.teacher,
            self.room,
            [self.class_group],
            start_dt,
            end_dt,
        )
        self.assertIsNone(error)


class EquipmentValidationTestCase(DatabaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.class_group = ClassGroup(name="INFO3", size=20)
        self.teacher = Teacher(name="Didier")
        self.room_without_equipment = Room(name="B101", capacity=24)
        self.room_with_equipment = Room(name="B102", capacity=24)
        self.projector = Equipment(name="Vidéoprojecteur")
        self.course = Course(
            name="TP - Audiovisuel - S1",
            course_type="TP",
            session_length_hours=2,
            sessions_required=1,
            semester="S1",
        )
        self.course.class_links.append(CourseClassLink(class_group=self.class_group))
        self.course.equipments.append(self.projector)
        self.room_with_equipment.equipments.append(self.projector)

        db.session.add_all(
            [
                self.class_group,
                self.teacher,
                self.room_without_equipment,
                self.room_with_equipment,
                self.projector,
                self.course,
            ]
        )
        db.session.commit()

        availabilities = [
            TeacherAvailability(
                teacher=self.teacher,
                weekday=weekday,
                start_time=time(8, 0),
                end_time=time(18, 0),
            )
            for weekday in range(5)
        ]
        db.session.add_all(availabilities)
        db.session.commit()

    def test_validation_blocks_room_missing_equipment(self) -> None:
        start_dt = datetime(2024, 1, 8, 8, 0, 0)
        end_dt = datetime(2024, 1, 8, 10, 0, 0)
        error = _validate_session_constraints(
            self.course,
            self.teacher,
            self.room_without_equipment,
            [self.class_group],
            start_dt,
            end_dt,
        )
        self.assertIsNotNone(error)
        self.assertIn("équipement", error.lower())

    def test_validation_allows_room_with_required_equipment(self) -> None:
        start_dt = datetime(2024, 1, 8, 10, 15, 0)
        end_dt = datetime(2024, 1, 8, 12, 15, 0)
        error = _validate_session_constraints(
            self.course,
            self.teacher,
            self.room_with_equipment,
            [self.class_group],
            start_dt,
            end_dt,
        )
        self.assertIsNone(error)


class ConfiguredHoursTestCase(DatabaseTestCase):
    def test_cm_total_required_hours_uses_configured_value(self) -> None:
        base_name = CourseName(name="Synthèse")
        course = Course(
            name=Course.compose_name("CM", base_name.name, "S1"),
            course_type="CM",
            session_length_hours=3,
            sessions_required=2,
            semester="S1",
            configured_name=base_name,
            cm_required_hours=18,
        )
        db.session.add_all([base_name, course])
        db.session.commit()

        self.assertEqual(course.total_required_hours, 18)

    def test_class_link_configured_hours_for_subgroups(self) -> None:
        course, link, class_group = self._create_tp_course()
        link.set_configured_hours(subgroup_a_hours=6, subgroup_b_hours=8)
        db.session.commit()

        self.assertEqual(link.configured_hours("A"), 6)
        self.assertEqual(link.configured_hours("B"), 8)

        teacher = Teacher(name="Alice")
        room = Room(name="B200", capacity=24)
        db.session.add_all([teacher, room])
        db.session.commit()

        session_a = Session(
            course=course,
            teacher=teacher,
            room=room,
            class_group=class_group,
            subgroup_label="A",
            start_time=datetime(2024, 1, 8, 8, 0),
            end_time=datetime(2024, 1, 8, 10, 0),
        )
        session_a.attendees = [class_group]
        db.session.add(session_a)
        db.session.commit()

        self.assertEqual(link.configured_hours("A"), 6)

    def test_total_required_hours_falls_back_to_sessions(self) -> None:
        base_name = CourseName(name="Analyse")
        course = Course(
            name=Course.compose_name("TD", base_name.name, "S1"),
            course_type="TD",
            session_length_hours=2,
            sessions_required=3,
            semester="S1",
            configured_name=base_name,
        )
        class_group = ClassGroup(name="INFO1", size=30)
        link = CourseClassLink(class_group=class_group, group_count=1)
        course.class_links.append(link)
        db.session.add_all([base_name, course, class_group])
        db.session.commit()

        self.assertEqual(course.total_required_hours, 6)

    def test_class_hours_needed_respects_configured_hours(self) -> None:
        base_name = CourseName(name="Physique")
        course = Course(
            name=Course.compose_name("TD", base_name.name, "S1"),
            course_type="TD",
            session_length_hours=2,
            sessions_required=3,
            semester="S1",
            configured_name=base_name,
        )
        class_group = ClassGroup(name="INFO2", size=28)
        link = CourseClassLink(class_group=class_group, group_count=1)
        course.class_links.append(link)
        teacher = Teacher(name="Alice")
        room = Room(name="B201", capacity=30)
        db.session.add_all([base_name, course, class_group, teacher, room])
        db.session.commit()

        link.set_configured_hours(class_hours=10)
        db.session.commit()

        session = Session(
            course=course,
            teacher=teacher,
            room=room,
            class_group=class_group,
            start_time=datetime(2024, 1, 8, 8, 0),
            end_time=datetime(2024, 1, 8, 11, 0),
        )
        session.attendees = [class_group]
        db.session.add(session)
        db.session.commit()

        remaining = _class_hours_needed(course, class_group)
        self.assertEqual(remaining, 7)

    def test_teacher_hour_summary_lists_configured_and_scheduled(self) -> None:
        course, link, class_group = self._create_tp_course()
        teacher_a = Teacher(name="Alice")
        teacher_b = Teacher(name="Bruno")
        room = Room(name="B204", capacity=24)
        db.session.add_all([teacher_a, teacher_b, room])
        db.session.commit()

        link.teacher_a = teacher_a
        link.teacher_b = teacher_b
        link.set_configured_hours(subgroup_a_hours=4, subgroup_b_hours=6)
        db.session.commit()

        session_a = Session(
            course=course,
            teacher=teacher_a,
            room=room,
            class_group=class_group,
            subgroup_label="A",
            start_time=datetime(2024, 1, 9, 8, 0),
            end_time=datetime(2024, 1, 9, 10, 0),
        )
        session_a.attendees = [class_group]
        session_b = Session(
            course=course,
            teacher=teacher_b,
            room=room,
            class_group=class_group,
            subgroup_label="B",
            start_time=datetime(2024, 1, 10, 8, 0),
            end_time=datetime(2024, 1, 10, 11, 0),
        )
        session_b.attendees = [class_group]
        db.session.add_all([session_a, session_b])
        db.session.commit()

        summary = course.teacher_hour_summary
        self.assertEqual(len(summary), 2)
        alice_entry = next(entry for entry in summary if entry["teacher"].name == "Alice")
        bruno_entry = next(entry for entry in summary if entry["teacher"].name == "Bruno")
        self.assertEqual(alice_entry["configured_hours"], 4)
        self.assertEqual(alice_entry["scheduled_hours"], 2)
        self.assertEqual(alice_entry["remaining_hours"], 2)
        self.assertEqual(bruno_entry["configured_hours"], 6)
        self.assertEqual(bruno_entry["scheduled_hours"], 3)
        self.assertEqual(bruno_entry["remaining_hours"], 3)


class SchedulerRelocationTestCase(DatabaseTestCase):
    def test_relocate_sessions_moves_latest_week(self) -> None:
        base_name = CourseName(name="Analyse")
        course = Course(
            name=Course.compose_name("TD", base_name.name, "S1"),
            course_type="TD",
            session_length_hours=2,
            sessions_required=2,
            semester="S1",
            configured_name=base_name,
        )
        class_group = ClassGroup(name="INFO1", size=24)
        link = CourseClassLink(class_group=class_group)
        course.class_links.append(link)
        teacher = Teacher(name="Alice")
        room = Room(name="A101", capacity=30)
        db.session.add_all([base_name, course, class_group, teacher, room])
        db.session.commit()

        first_start = datetime(2025, 9, 8, 8, 0)
        first_end = datetime(2025, 9, 8, 10, 0)
        first_session = Session(
            course=course,
            teacher=teacher,
            room=room,
            class_group=class_group,
            start_time=first_start,
            end_time=first_end,
        )
        first_session.attendees = [class_group]

        second_start = datetime(2025, 9, 15, 8, 0)
        second_end = datetime(2025, 9, 15, 10, 0)
        second_session = Session(
            course=course,
            teacher=teacher,
            room=room,
            class_group=class_group,
            start_time=second_start,
            end_time=second_end,
        )
        second_session.attendees = [class_group]

        db.session.add_all([first_session, second_session])
        db.session.commit()

        per_day_hours = {
            first_start.date(): first_session.duration_hours,
            second_start.date(): second_session.duration_hours,
        }
        weekday_frequencies = Counter({first_start.weekday(): 2})
        created_sessions: list[Session] = []
        attempted_weeks: set[date] = set()

        removed = _relocate_sessions_for_groups(
            course=course,
            class_groups=[class_group],
            created_sessions=created_sessions,
            per_day_hours=per_day_hours,
            weekday_frequencies=weekday_frequencies,
            reporter=None,
            attempted_weeks=attempted_weeks,
            subgroup_label=None,
            context_label=class_group.name,
        )

        self.assertEqual(removed, 2)
        self.assertEqual(attempted_weeks, {date(2025, 9, 15)})
        remaining = Session.query.filter_by(course=course).all()
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0].start_time.date(), date(2025, 9, 8))
        self.assertEqual(per_day_hours[first_start.date()], 2)
        self.assertEqual(per_day_hours.get(second_start.date(), 0), 0)
        self.assertEqual(weekday_frequencies[first_start.weekday()], 1)

        second_attempt = _relocate_sessions_for_groups(
            course=course,
            class_groups=[class_group],
            created_sessions=created_sessions,
            per_day_hours=per_day_hours,
            weekday_frequencies=weekday_frequencies,
            reporter=None,
            attempted_weeks=attempted_weeks,
            subgroup_label=None,
            context_label=class_group.name,
        )

        self.assertEqual(second_attempt, 2)
        self.assertEqual(attempted_weeks, {date(2025, 9, 15), date(2025, 9, 8)})
        self.assertEqual(Session.query.filter_by(course=course).count(), 0)
        self.assertEqual(per_day_hours[first_start.date()], 0)
        self.assertEqual(weekday_frequencies.get(first_start.weekday(), 0), 0)


class ScheduleGenerationFailureTestCase(DatabaseTestCase):
    def test_generate_schedule_raises_when_no_room_available(self) -> None:
        course, link, _ = self._create_tp_course()

        teacher = Teacher(name="Alice")
        db.session.add(teacher)
        db.session.commit()

        availability = TeacherAvailability(
            teacher=teacher,
            weekday=0,
            start_time=time(8, 0),
            end_time=time(18, 0),
        )
        db.session.add(availability)
        db.session.commit()

        link.teacher_a = teacher
        course.teachers.append(teacher)
        db.session.commit()

        with self.assertRaises(ValueError) as context:
            generate_schedule(course)

        self.assertIn(
            "Impossible de générer automatiquement toutes les séances",
            str(context.exception),
        )


if __name__ == "__main__":
    unittest.main()
