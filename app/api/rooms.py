"""Room CRUD endpoints."""
from __future__ import annotations

from typing import Any

from flask import request
from flask_restx import Namespace, Resource, fields

from ..extensions import db
from ..models import Room, RoomEquipment


ns = Namespace("rooms", description="CRUD operations for rooms")

equipment_model = ns.model(
    "RoomEquipment",
    {
        "id": fields.Integer(readonly=True),
        "key": fields.String(required=True),
        "value": fields.String(required=True),
    },
)

room_model = ns.model(
    "Room",
    {
        "id": fields.Integer(readonly=True),
        "name": fields.String(required=True),
        "capacity": fields.Integer(required=True),
        "building": fields.String,
        "equipment": fields.List(fields.Nested(equipment_model)),
    },
)


def serialize_room(room: Room) -> dict[str, Any]:
    return {
        "id": room.id,
        "name": room.name,
        "capacity": room.capacity,
        "building": room.building,
        "equipment": [
            {"id": equipment.id, "key": equipment.key, "value": equipment.value}
            for equipment in room.equipment
        ],
    }


@ns.route("")
class RoomList(Resource):
    @ns.marshal_list_with(room_model)
    def get(self) -> list[dict[str, Any]]:
        rooms = Room.query.order_by(Room.name).all()
        return [serialize_room(room) for room in rooms]

    @ns.expect(room_model, validate=True)
    @ns.marshal_with(room_model, code=201)
    def post(self) -> dict[str, Any]:
        payload = request.json or {}
        room = Room(
            name=payload["name"],
            capacity=payload["capacity"],
            building=payload.get("building"),
        )
        db.session.add(room)
        db.session.flush()
        _sync_equipment(room, payload.get("equipment", []))
        db.session.commit()
        return serialize_room(room), 201


@ns.route("/<int:room_id>")
class RoomResource(Resource):
    @ns.marshal_with(room_model)
    def get(self, room_id: int) -> dict[str, Any]:
        room = Room.query.get_or_404(room_id)
        return serialize_room(room)

    @ns.expect(room_model, validate=True)
    @ns.marshal_with(room_model)
    def put(self, room_id: int) -> dict[str, Any]:
        room = Room.query.get_or_404(room_id)
        payload = request.json or {}
        room.name = payload["name"]
        room.capacity = payload["capacity"]
        room.building = payload.get("building")
        _sync_equipment(room, payload.get("equipment", []))
        db.session.commit()
        return serialize_room(room)

    def delete(self, room_id: int) -> tuple[dict[str, str], int]:
        room = Room.query.get_or_404(room_id)
        db.session.delete(room)
        db.session.commit()
        return {"status": "deleted"}, 204


def _sync_equipment(room: Room, payload: list[dict[str, Any]]) -> None:
    room.equipment.clear()
    for item in payload:
        equipment = RoomEquipment(room=room, key=item["key"], value=item["value"])
        room.equipment.append(equipment)
