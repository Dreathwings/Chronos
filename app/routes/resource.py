from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy import select

from .. import db
from ..models import Logiciel, Materiel

bp = Blueprint("resource", __name__)


@bp.route("/logiciel", methods=["GET", "POST"])
def list_logiciels():
    if request.method == "POST":
        logiciel = Logiciel(
            nom=request.form.get("nom"),
            version=request.form.get("version") or None,
        )
        db.session.add(logiciel)
        db.session.commit()
        flash("Logiciel créé", "success")
        return redirect(url_for("resource.list_logiciels"))

    logiciels = db.session.scalars(select(Logiciel).order_by(Logiciel.nom)).all()
    return render_template("resource/logiciel.html", logiciels=logiciels)


@bp.route("/materiel", methods=["GET", "POST"])
def list_materiels():
    if request.method == "POST":
        materiel = Materiel(
            nom=request.form.get("nom"),
            description=request.form.get("description") or None,
        )
        db.session.add(materiel)
        db.session.commit()
        flash("Matériel créé", "success")
        return redirect(url_for("resource.list_materiels"))

    materiels = db.session.scalars(select(Materiel).order_by(Materiel.nom)).all()
    return render_template("resource/materiel.html", materiels=materiels)
