"""Timeslot endpoints including automatic generation with Chronos rules."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from flask import request
from flask_restx import Namespace, Resource, fields

from ..extensions import db
from ..models import Timeslot


ns = Namespace("timeslots", description="Manage potential teaching slots")

STANDARD_DAY_SLOTS: list[tuple[time, time]] = [
    (time(8, 0), time(9, 0)),
    (time(9, 0), time(10, 0)),
    (time(10, 15), time(11, 15)),
    (time(11, 15), time(12, 15)),
    (time(13, 30), time(14, 30)),
    (time(14, 30), time(15, 30)),
    (time(15, 45), time(16, 45)),
    (time(16, 45), time(17, 45)),
]


timeslot_model = ns.model(
    "Timeslot",
    {
        "id": fields.Integer(readonly=True),
        "date": fields.String(required=True, description="YYYY-MM-DD"),
        "start_time": fields.String(required=True, description="HH:MM"),
        "end_time": fields.String(required=True, description="HH:MM"),
        "minutes": fields.Integer(required=True),
    },
)


def serialize_timeslot(timeslot: Timeslot) -> dict[str, Any]:
    return {
        "id": timeslot.id,
        "date": timeslot.date.isoformat(),
        "start_time": timeslot.start_time.strftime("%H:%M"),
        "end_time": timeslot.end_time.strftime("%H:%M"),
        "minutes": timeslot.minutes,
    }


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _parse_time(value: str) -> time:
    return datetime.strptime(value, "%H:%M").time()


@ns.route("")
class TimeslotList(Resource):
    @ns.marshal_list_with(timeslot_model)
    def get(self) -> list[dict[str, Any]]:
        timeslots = Timeslot.query.order_by(Timeslot.date, Timeslot.start_time).all()
        return [serialize_timeslot(timeslot) for timeslot in timeslots]


generate_model = ns.model(
    "TimeslotGeneration",
    {
        "start_date": fields.String(required=True, description="YYYY-MM-DD"),
        "end_date": fields.String(required=True, description="YYYY-MM-DD"),
        "weekdays": fields.List(
            fields.Integer, required=True, description="0=Monday, 6=Sunday"
        ),
        "start_time": fields.String(required=True, description="HH:MM"),
        "end_time": fields.String(required=True, description="HH:MM"),
        "slot_minutes": fields.Integer(
            required=True, description="Duration of each slot in minutes"
        ),
        "clear_existing": fields.Boolean(
            default=False, description="Remove existing timeslots in range"
        ),
    },
)


@ns.route("/generate")
class TimeslotGenerate(Resource):
    @ns.expect(generate_model, validate=True)
    @ns.marshal_list_with(timeslot_model)
    def post(self) -> list[dict[str, Any]]:
        payload = request.json or {}
        start_date = _parse_date(payload["start_date"])
        end_date = _parse_date(payload["end_date"])
        weekdays = set(payload.get("weekdays", []))
        day_start_time = _parse_time(payload["start_time"])
        day_end_time = _parse_time(payload["end_time"])
        slot_minutes = int(payload["slot_minutes"])

        if start_date > end_date:
            ns.abort(400, "start_date must be before end_date")
        if slot_minutes != 60:
            ns.abort(400, "Les créneaux doivent durer 60 minutes.")
        expected_start = STANDARD_DAY_SLOTS[0][0]
        expected_end = STANDARD_DAY_SLOTS[-1][1]
        if day_start_time > expected_start or day_end_time < expected_end:
            ns.abort(
                400,
                "La plage journalière doit couvrir au minimum 08:00 à 17:45 pour respecter les pauses.",
            )

        if payload.get("clear_existing"):
            Timeslot.query.filter(
                Timeslot.date >= start_date, Timeslot.date <= end_date
            ).delete(synchronize_session=False)

        created: list[Timeslot] = []
        current_date = start_date
        while current_date <= end_date:
            if not weekdays or current_date.weekday() in weekdays:
                _create_slots_for_day(
                    created,
                    current_date,
                    day_start_time,
                    day_end_time,
                    slot_minutes,
                )
            current_date += timedelta(days=1)

        if not created:
            ns.abort(400, "Aucun créneau généré pour la période demandée.")

        db.session.add_all(created)
        db.session.commit()
        return [serialize_timeslot(timeslot) for timeslot in created]


def _create_slots_for_day(
    collection: list[Timeslot],
    current_date: date,
    day_start: time,
    day_end: time,
    slot_minutes: int,
) -> None:
    added = False
    for slot_start, slot_end in STANDARD_DAY_SLOTS:
        if slot_start < day_start or slot_end > day_end:
            continue
        collection.append(
            Timeslot(
                date=current_date,
                start_time=slot_start,
                end_time=slot_end,
                minutes=slot_minutes,
            )
        )
        added = True
    if not added:
        ns.abort(400, "Aucun créneau ne correspond à la plage demandée.")
