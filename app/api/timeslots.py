"""Timeslot endpoints including automatic generation."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from flask import request
from flask_restx import Namespace, Resource, fields

from ..extensions import db
from ..models import Timeslot


ns = Namespace("timeslots", description="Manage potential teaching slots")

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


def _parse_date(value: str) -> datetime.date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _parse_time(value: str) -> datetime.time:
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
        start_time = _parse_time(payload["start_time"])
        end_time = _parse_time(payload["end_time"])
        slot_minutes = int(payload["slot_minutes"])

        if start_date > end_date:
            ns.abort(400, "start_date must be before end_date")
        if start_time >= end_time:
            ns.abort(400, "start_time must be before end_time")
        if slot_minutes <= 0:
            ns.abort(400, "slot_minutes must be positive")

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
                    start_time,
                    end_time,
                    slot_minutes,
                )
            current_date += timedelta(days=1)

        db.session.add_all(created)
        db.session.commit()
        return [serialize_timeslot(timeslot) for timeslot in created]


def _create_slots_for_day(
    collection: list[Timeslot],
    current_date: datetime.date,
    start_time: datetime.time,
    end_time: datetime.time,
    slot_minutes: int,
) -> None:
    start_dt = datetime.combine(current_date, start_time)
    end_dt = datetime.combine(current_date, end_time)

    while start_dt + timedelta(minutes=slot_minutes) <= end_dt:
        end_slot = start_dt + timedelta(minutes=slot_minutes)
        collection.append(
            Timeslot(
                date=current_date,
                start_time=start_dt.time(),
                end_time=end_slot.time(),
                minutes=slot_minutes,
            )
        )
        start_dt = end_slot
