"""Populate the database with sample data for Chronos."""
from __future__ import annotations

from datetime import date, time, timedelta

from app import create_app
from app.extensions import db
from app.models import (
    ClassGroup,
    Course,
    CourseRequirement,
    Room,
    RoomEquipment,
    Teacher,
    TeacherAvailability,
    Timeslot,
)


SAMPLE_DATA = {
    "teachers": [
        {
            "name": "Alice Martin",
            "max_weekly_load_hrs": 12,
            "availabilities": [
                {"weekday": 0, "start_time": time(8, 0), "end_time": time(16, 0)},
                {"weekday": 2, "start_time": time(8, 0), "end_time": time(16, 0)},
            ],
        },
        {
            "name": "Benoit Leroy",
            "max_weekly_load_hrs": 16,
            "availabilities": [
                {"weekday": 1, "start_time": time(9, 0), "end_time": time(18, 0)},
                {"weekday": 3, "start_time": time(9, 0), "end_time": time(18, 0)},
            ],
        },
    ],
    "class_groups": [
        {
            "code": "IG1",
            "name": "Informatique Groupe 1",
            "size": 18,
            "notes": "Licence",
        },
        {
            "code": "IG2",
            "name": "Informatique Groupe 2",
            "size": 25,
            "notes": "Licence",
        },
    ],
    "rooms": [
        {
            "name": "Salle A",
            "capacity": 30,
            "building": "B1",
            "equipment": {"projector": "true", "pc": "true"},
        },
        {
            "name": "Salle B",
            "capacity": 20,
            "building": "B1",
            "equipment": {"projector": "true"},
        },
    ],
    "courses": [
        {
            "name": "Informatique 101",
            "group_id": "IG1",
            "size": 18,
            "teacher": "Alice Martin",
            "sessions_count": 2,
            "session_minutes": 120,
            "window_start": date.today(),
            "window_end": date.today() + timedelta(days=7),
            "requirements": {"pc": "true"},
        },
        {
            "name": "Gestion de projet",
            "group_id": "IG2",
            "size": 25,
            "teacher": "Benoit Leroy",
            "sessions_count": 2,
            "session_minutes": 120,
            "window_start": date.today(),
            "window_end": date.today() + timedelta(days=7),
            "requirements": {"projector": "true"},
        },
    ],
}


def seed() -> None:
    db.drop_all()
    db.create_all()

    teachers: dict[str, Teacher] = {}
    for teacher_data in SAMPLE_DATA["teachers"]:
        teacher = Teacher(
            name=teacher_data["name"],
            max_weekly_load_hrs=teacher_data["max_weekly_load_hrs"],
        )
        for availability in teacher_data["availabilities"]:
            teacher.availabilities.append(TeacherAvailability(**availability))
        db.session.add(teacher)
        teachers[teacher.name] = teacher

    rooms: dict[str, Room] = {}
    for room_data in SAMPLE_DATA["rooms"]:
        data = room_data.copy()
        equipment = data.pop("equipment")
        room = Room(**data)
        for key, value in equipment.items():
            room.equipment.append(RoomEquipment(key=key, value=value))
        db.session.add(room)
        rooms[room.name] = room

    for class_data in SAMPLE_DATA["class_groups"]:
        class_group = ClassGroup(**class_data)
        db.session.add(class_group)

    for course_data in SAMPLE_DATA["courses"]:
        data = course_data.copy()
        requirements = data.pop("requirements")
        teacher_name = data.pop("teacher")
        course = Course(teacher=teachers[teacher_name], **data)
        for key, value in requirements.items():
            course.requirements.append(CourseRequirement(key=key, value=value))
        db.session.add(course)

    base_date = date.today()
    for day_offset in range(5):
        day = base_date + timedelta(days=day_offset)
        for start_hour in (8, 10, 14):
            db.session.add(
                Timeslot(
                    date=day,
                    start_time=time(start_hour, 0),
                    end_time=time(start_hour + 2, 0),
                    minutes=120,
                )
            )

    db.session.commit()
    print("Seed completed")


if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        seed()
