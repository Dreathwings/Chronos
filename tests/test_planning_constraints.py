from datetime import datetime, time

import pytest

from app.models import (
    ClassGroup,
    Course,
    CourseClassLink,
    Equipment,
    Room,
    Teacher,
    TeacherAvailability,
)
from app.planning.constraints import ReasonCode, SessionRequest, can_place


@pytest.fixture()
def base_entities(session):
    teacher = Teacher(name="Alice")
    class_group = ClassGroup(name="INFO1", size=30)
    course = Course(
        name="Math S1",
        course_type="TD",
        semester="S1",
        session_length_hours=2,
        sessions_required=1,
    )
    link = CourseClassLink(class_group=class_group)
    course.class_links.append(link)
    room = Room(name="B101", capacity=40, computers=10)
    session.add_all([teacher, class_group, course, room])
    session.commit()
    return {
        "teacher": teacher,
        "class_group": class_group,
        "course": course,
        "link": link,
        "room": room,
    }


def _add_teacher_availability(session, teacher, weekday: int, start: time, end: time) -> None:
    session.add(
        TeacherAvailability(
            teacher=teacher,
            weekday=weekday,
            start_time=start,
            end_time=end,
        )
    )
    session.commit()


def test_can_place_success(base_entities, session):
    teacher = base_entities["teacher"]
    class_group = base_entities["class_group"]
    course = base_entities["course"]
    room = base_entities["room"]
    link = base_entities["link"]
    _add_teacher_availability(session, teacher, 0, time(8, 0), time(12, 0))

    start = datetime(2025, 9, 1, 8, 0)
    end = datetime(2025, 9, 1, 10, 0)
    request = SessionRequest(
        course=course,
        class_groups=[class_group],
        subgroup_label=None,
        duration_hours=2,
        link=link,
        primary_link=None,
    )

    violations = can_place(
        request,
        teacher=teacher,
        rooms=[room],
        segments=[(start, end)],
    )

    assert violations == []


def test_can_place_fails_teacher_unavailable(base_entities, session):
    teacher = base_entities["teacher"]
    class_group = base_entities["class_group"]
    course = base_entities["course"]
    room = base_entities["room"]
    link = base_entities["link"]
    _add_teacher_availability(session, teacher, 0, time(13, 0), time(17, 0))

    start = datetime(2025, 9, 1, 8, 0)
    end = datetime(2025, 9, 1, 10, 0)
    request = SessionRequest(
        course=course,
        class_groups=[class_group],
        subgroup_label=None,
        duration_hours=2,
        link=link,
        primary_link=None,
    )

    violations = can_place(
        request,
        teacher=teacher,
        rooms=[room],
        segments=[(start, end)],
    )

    assert ReasonCode.TEACHER_UNAVAILABLE in {violation.code for violation in violations}


def test_can_place_fails_room_capacity(base_entities, session):
    teacher = base_entities["teacher"]
    class_group = base_entities["class_group"]
    course = base_entities["course"]
    link = base_entities["link"]
    room = Room(name="B102", capacity=10, computers=10)
    session.add(room)
    session.commit()
    _add_teacher_availability(session, teacher, 0, time(8, 0), time(12, 0))

    start = datetime(2025, 9, 1, 8, 0)
    end = datetime(2025, 9, 1, 10, 0)
    request = SessionRequest(
        course=course,
        class_groups=[class_group],
        subgroup_label=None,
        duration_hours=2,
        link=link,
        primary_link=None,
    )

    violations = can_place(
        request,
        teacher=teacher,
        rooms=[room],
        segments=[(start, end)],
    )

    assert ReasonCode.ROOM_CAPACITY in {violation.code for violation in violations}


def test_can_place_fails_equipment_requirement(base_entities, session):
    teacher = base_entities["teacher"]
    class_group = base_entities["class_group"]
    course = base_entities["course"]
    room = base_entities["room"]
    link = base_entities["link"]
    equipment = Equipment(name="Projecteur")
    course.equipments.append(equipment)
    session.add(equipment)
    session.commit()
    _add_teacher_availability(session, teacher, 0, time(8, 0), time(12, 0))

    start = datetime(2025, 9, 1, 8, 0)
    end = datetime(2025, 9, 1, 10, 0)
    request = SessionRequest(
        course=course,
        class_groups=[class_group],
        subgroup_label=None,
        duration_hours=2,
        link=link,
        primary_link=None,
    )

    violations = can_place(
        request,
        teacher=teacher,
        rooms=[room],
        segments=[(start, end)],
    )

    assert ReasonCode.ROOM_EQUIPMENT in {violation.code for violation in violations}


def test_can_place_fails_teacher_allocation(base_entities, session):
    teacher = base_entities["teacher"]
    class_group = base_entities["class_group"]
    course = base_entities["course"]
    room = base_entities["room"]
    link = base_entities["link"]
    _add_teacher_availability(session, teacher, 0, time(8, 0), time(12, 0))

    class AllocationState:
        def can_allocate(self, teacher_id, duration_hours):
            return False

    start = datetime(2025, 9, 1, 8, 0)
    end = datetime(2025, 9, 1, 10, 0)
    request = SessionRequest(
        course=course,
        class_groups=[class_group],
        subgroup_label=None,
        duration_hours=2,
        link=link,
        primary_link=None,
    )

    violations = can_place(
        request,
        teacher=teacher,
        rooms=[room],
        segments=[(start, end)],
        allocation_state=AllocationState(),
    )

    assert ReasonCode.TEACHER_ALLOCATION in {violation.code for violation in violations}
