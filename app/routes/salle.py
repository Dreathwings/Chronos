from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy import select

from .. import db
from ..models import Salle, Session

bp = Blueprint("salle", __name__, url_prefix="/salle")


@bp.route("", methods=["GET", "POST"])
def list_salles():
    if request.method == "POST":
        salle = Salle(
            nom=request.form.get("nom"),
            capacite=int(request.form.get("capacite") or 0),
            nombre_pc=int(request.form.get("nombre_pc") or 0),
            equipements=request.form.get("equipements") or None,
        )
        db.session.add(salle)
        db.session.commit()
        flash("Salle créée", "success")
        return redirect(url_for("salle.list_salles"))

    salles = db.session.scalars(select(Salle).order_by(Salle.nom)).all()
    return render_template("salle/list.html", salles=salles)


@bp.route("/<int:salle_id>", methods=["GET", "POST"])
def detail_salle(salle_id: int):
    salle = db.session.get(Salle, salle_id)
    if not salle:
        flash("Salle introuvable", "warning")
        return redirect(url_for("salle.list_salles"))

    if request.method == "POST":
        salle.nom = request.form.get("nom") or salle.nom
        salle.capacite = int(request.form.get("capacite") or salle.capacite)
        salle.nombre_pc = int(request.form.get("nombre_pc") or salle.nombre_pc)
        salle.equipements = request.form.get("equipements") or None
        db.session.commit()
        flash("Salle mise à jour", "success")
        return redirect(url_for("salle.detail_salle", salle_id=salle.id))

    sessions = db.session.scalars(select(Session).where(Session.salle_id == salle.id)).all()
    return render_template("salle/detail.html", salle=salle, sessions=sessions)
