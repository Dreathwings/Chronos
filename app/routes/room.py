"""Room management routes."""
from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy.orm import joinedload

from .. import db
from ..models import CourseSession, Room

bp = Blueprint("room", __name__)


@bp.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        capacity = request.form.get("capacity", "").strip()
        has_computers = bool(request.form.get("has_computers"))
        equipment_notes = request.form.get("equipment_notes") or None

        if not name or not capacity.isdigit():
            flash("Nom et capacité sont obligatoires", "danger")
        else:
            room = Room(
                name=name,
                capacity=int(capacity),
                has_computers=has_computers,
                equipment_notes=equipment_notes,
            )
            db.session.add(room)
            db.session.commit()
            flash("Salle créée", "success")
            return redirect(url_for("room.index"))

    rooms = Room.query.order_by(Room.name).all()
    return render_template("salle/index.html", rooms=rooms)


@bp.route("/<int:room_id>", methods=["GET", "POST"])
def detail(room_id: int):
    room = (
        Room.query.options(joinedload(Room.sessions).joinedload(CourseSession.course))
        .filter_by(id=room_id)
        .first_or_404()
    )

    if request.method == "POST":
        room.name = request.form.get("name", room.name)
        room.capacity = int(request.form.get("capacity", room.capacity))
        room.has_computers = bool(request.form.get("has_computers"))
        room.equipment_notes = request.form.get("equipment_notes") or None
        db.session.commit()
        flash("Salle mise à jour", "success")
        return redirect(url_for("room.detail", room_id=room.id))

    events = [session.as_fullcalendar_event() for session in room.sessions]
    return render_template("salle/detail.html", room=room, events=events)
