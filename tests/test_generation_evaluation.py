import json
import unittest
from datetime import datetime, time

from app import create_app, db
from app.models import (
    ClassGroup,
    Course,
    CourseClassLink,
    CourseName,
    CourseScheduleLog,
    Room,
    Session,
    Teacher,
    TeacherAvailability,
)
from app.routes import _evaluate_course_generation
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


class GenerationEvaluationTestCase(DatabaseTestCase):
    def _create_course_setup(self, *, sessions_required: int = 2) -> Course:
        base_name = CourseName(name="Maths")
        course = Course(
            name=Course.compose_name("TD", base_name.name, "S1"),
            course_type="TD",
            session_length_hours=2,
            sessions_required=sessions_required,
            semester="S1",
            configured_name=base_name,
        )
        class_group = ClassGroup(name="INFO1", size=24)
        link = CourseClassLink(class_group=class_group)
        course.class_links.append(link)

        teacher = Teacher(name="Alice")
        room = Room(name="B101", capacity=30)

        course.teachers.append(teacher)
        db.session.add_all([base_name, course, class_group, teacher, room])
        db.session.commit()

        availabilities = [
            TeacherAvailability(
                teacher=teacher,
                weekday=weekday,
                start_time=time(8, 0),
                end_time=time(18, 0),
            )
            for weekday in range(5)
        ]
        db.session.add_all(availabilities)
        db.session.commit()

        return db.session.get(Course, course.id)

    def test_course_with_valid_sessions_is_successful(self) -> None:
        course = self._create_course_setup(sessions_required=1)
        teacher = course.teachers[0]
        room = Room.query.first()
        class_group = course.class_links[0].class_group

        session = Session(
            course=course,
            teacher=teacher,
            room=room,
            class_group=class_group,
            start_time=datetime(2024, 1, 8, 8, 0, 0),
            end_time=datetime(2024, 1, 8, 10, 0, 0),
        )
        session.attendees = [class_group]
        db.session.add(session)
        db.session.commit()

        refreshed = db.session.get(Course, course.id)
        result = _evaluate_course_generation(refreshed)

        self.assertEqual(result["status"], "success")
        self.assertGreaterEqual(refreshed.scheduled_hours, 2)
        self.assertTrue(any("planifiées" in message for message in result["messages"]))

    def test_missing_hours_triggers_warning(self) -> None:
        course = self._create_course_setup()
        refreshed = db.session.get(Course, course.id)

        result = _evaluate_course_generation(refreshed)

        self.assertEqual(result["status"], "warning")
        self.assertTrue(any("Heures manquantes" in message for message in result["messages"]))

    def test_constraint_violation_marks_error(self) -> None:
        course = self._create_course_setup(sessions_required=1)
        teacher = course.teachers[0]
        room = Room.query.first()
        class_group = course.class_links[0].class_group

        session = Session(
            course=course,
            teacher=teacher,
            room=room,
            class_group=class_group,
            start_time=datetime(2024, 1, 13, 8, 0, 0),
            end_time=datetime(2024, 1, 13, 10, 0, 0),
        )
        session.attendees = [class_group]
        db.session.add(session)
        db.session.commit()

        refreshed = db.session.get(Course, course.id)
        result = _evaluate_course_generation(refreshed)

        self.assertEqual(result["status"], "error")
        self.assertTrue(any("lundi au vendredi" in message for message in result["messages"]))

    def test_teacher_permutation_alert_included(self) -> None:
        course = self._create_course_setup(sessions_required=1)
        teacher = course.teachers[0]
        room = Room.query.first()
        class_group = course.class_links[0].class_group

        session = Session(
            course=course,
            teacher=teacher,
            room=room,
            class_group=class_group,
            start_time=datetime(2024, 1, 8, 8, 0, 0),
            end_time=datetime(2024, 1, 8, 10, 0, 0),
        )
        session.attendees = [class_group]
        db.session.add(session)
        db.session.commit()

        log = CourseScheduleLog(
            course=course,
            status="warning",
            summary="Permutation automatique des enseignants",
            messages=json.dumps(
                [
                    {
                        "level": "warning",
                        "message": "INFO1 — Classe entière : Alice → Bob",
                        "code": "teacher-permutation",
                    }
                ],
                ensure_ascii=False,
            ),
        )
        db.session.add(log)
        db.session.commit()

        refreshed = db.session.get(Course, course.id)
        result = _evaluate_course_generation(refreshed)

        self.assertEqual(result["status"], "warning")
        self.assertTrue(
            any("Permutation automatique des enseignants" in message for message in result["messages"])
        )
        self.assertTrue(
            any("Affectation ajustée" in message for message in result["messages"])
        )

    def test_tp_missing_td_marks_error(self) -> None:
        base_name = CourseName(name="Physique")
        class_group = ClassGroup(name="INFO2", size=24)
        td_course = Course(
            name=Course.compose_name("TD", base_name.name, "S1"),
            course_type="TD",
            session_length_hours=2,
            sessions_required=1,
            semester="S1",
            configured_name=base_name,
        )
        tp_course = Course(
            name=Course.compose_name("TP", base_name.name, "S1"),
            course_type="TP",
            session_length_hours=2,
            sessions_required=1,
            semester="S1",
            configured_name=base_name,
        )
        td_course.class_links.append(CourseClassLink(class_group=class_group, group_count=2))
        tp_course.class_links.append(CourseClassLink(class_group=class_group, group_count=2))

        teacher = Teacher(name="Paul")
        room = Room(name="C101", capacity=28)

        db.session.add_all([base_name, class_group, td_course, tp_course, teacher, room])
        db.session.commit()

        availabilities = [
            TeacherAvailability(
                teacher=teacher,
                weekday=weekday,
                start_time=time(8, 0),
                end_time=time(18, 0),
            )
            for weekday in range(5)
        ]
        db.session.add_all(availabilities)
        db.session.commit()

        td_session = Session(
            course=td_course,
            teacher=teacher,
            room=room,
            class_group=class_group,
            subgroup_label="A",
            start_time=datetime(2024, 1, 8, 8, 0, 0),
            end_time=datetime(2024, 1, 8, 10, 0, 0),
        )
        td_session.attendees = [class_group]

        tp_session = Session(
            course=tp_course,
            teacher=teacher,
            room=room,
            class_group=class_group,
            subgroup_label="A",
            start_time=datetime(2024, 1, 10, 10, 15, 0),
            end_time=datetime(2024, 1, 10, 12, 15, 0),
        )
        tp_session.attendees = [class_group]

        db.session.add_all([td_session, tp_session])
        db.session.commit()

        refreshed = db.session.get(Course, tp_course.id)
        result = _evaluate_course_generation(refreshed)

        self.assertEqual(result["status"], "error")
        self.assertTrue(
            any("TD des deux demi-groupes" in message for message in result["messages"])
        )

    def test_tp_without_td_course_is_allowed(self) -> None:
        base_name = CourseName(name="Chimie")
        class_group = ClassGroup(name="INFO3", size=24)
        tp_course = Course(
            name=Course.compose_name("TP", base_name.name, "S1"),
            course_type="TP",
            session_length_hours=2,
            sessions_required=1,
            semester="S1",
            configured_name=base_name,
        )
        tp_course.class_links.append(CourseClassLink(class_group=class_group, group_count=2))

        teacher = Teacher(name="Zoé")
        room = Room(name="D201", capacity=28)

        db.session.add_all([base_name, class_group, tp_course, teacher, room])
        db.session.commit()

        availabilities = [
            TeacherAvailability(
                teacher=teacher,
                weekday=weekday,
                start_time=time(8, 0),
                end_time=time(18, 0),
            )
            for weekday in range(5)
        ]
        db.session.add_all(availabilities)
        db.session.commit()

        session = Session(
            course=tp_course,
            teacher=teacher,
            room=room,
            class_group=class_group,
            subgroup_label="A",
            start_time=datetime(2024, 1, 15, 8, 0, 0),
            end_time=datetime(2024, 1, 15, 10, 0, 0),
        )
        session.attendees = [class_group]
        db.session.add(session)
        db.session.commit()

        refreshed = db.session.get(Course, tp_course.id)
        result = _evaluate_course_generation(refreshed)

        self.assertNotEqual(result["status"], "error")
        self.assertFalse(
            any("TD des deux demi-groupes" in message for message in result["messages"])
        )


class DashboardEvaluationTriggerTestCase(DatabaseTestCase):
    def _create_basic_course(self) -> Course:
        base_name = CourseName(name="Programmation")
        course = Course(
            name=Course.compose_name("TD", base_name.name, "S1"),
            course_type="TD",
            session_length_hours=2,
            sessions_required=1,
            semester="S1",
            configured_name=base_name,
        )
        class_group = ClassGroup(name="INFO1", size=24)
        link = CourseClassLink(class_group=class_group)
        course.class_links.append(link)

        teacher = Teacher(name="Alice")
        room = Room(name="B201", capacity=30)

        course.teachers.append(teacher)
        db.session.add_all([base_name, course, class_group, teacher, room])
        db.session.commit()

        availabilities = [
            TeacherAvailability(
                teacher=teacher,
                weekday=weekday,
                start_time=time(8, 0),
                end_time=time(18, 0),
            )
            for weekday in range(5)
        ]
        db.session.add_all(availabilities)
        db.session.commit()

        session = Session(
            course=course,
            teacher=teacher,
            room=room,
            class_group=class_group,
            start_time=datetime(2024, 1, 8, 8, 0, 0),
            end_time=datetime(2024, 1, 8, 10, 0, 0),
        )
        session.attendees = [class_group]
        db.session.add(session)
        db.session.commit()

        return db.session.get(Course, course.id)

    def test_dashboard_get_does_not_run_evaluation(self) -> None:
        client = self.app.test_client()
        prefix = self.app.config.get("URL_PREFIX", "") or ""
        response = client.get(f"{prefix}/")
        html = response.get_data(as_text=True)

        self.assertIn("Lancer la vérification", html)
        self.assertNotIn("Respectés :", html)

    def test_dashboard_post_runs_evaluation(self) -> None:
        self._create_basic_course()

        client = self.app.test_client()
        prefix = self.app.config.get("URL_PREFIX", "") or ""
        response = client.post(f"{prefix}/", data={"form": "evaluate-generation"})
        html = response.get_data(as_text=True)

        self.assertIn("Respectés :", html)
        self.assertIn("Tous les cours respectent les critères définis.", html)


if __name__ == "__main__":
    unittest.main()
