from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy import select

from .. import db
from ..models import Enseignant, Session

bp = Blueprint("enseignant", __name__, url_prefix="/enseignant")


@bp.route("", methods=["GET", "POST"])
def list_enseignants():
    if request.method == "POST":
        nom = request.form.get("nom")
        email = request.form.get("email")
        max_heures = request.form.get("max_heures_semaine")
        disponibilites = request.form.get("disponibilites")
        indisponibilites = request.form.get("indisponibilites")
        enseignant = Enseignant(
            nom=nom,
            email=email or None,
            max_heures_semaine=int(max_heures or 20),
            disponibilites=disponibilites or None,
            indisponibilites=indisponibilites or None,
        )
        db.session.add(enseignant)
        db.session.commit()
        flash("Enseignant créé", "success")
        return redirect(url_for("enseignant.list_enseignants"))

    enseignants = db.session.scalars(select(Enseignant).order_by(Enseignant.nom)).all()
    return render_template("enseignant/list.html", enseignants=enseignants)


@bp.route("/<int:enseignant_id>", methods=["GET", "POST"])
def detail_enseignant(enseignant_id: int):
    enseignant = db.session.get(Enseignant, enseignant_id)
    if not enseignant:
        flash("Enseignant introuvable", "warning")
        return redirect(url_for("enseignant.list_enseignants"))

    if request.method == "POST":
        enseignant.nom = request.form.get("nom") or enseignant.nom
        enseignant.email = request.form.get("email") or None
        enseignant.max_heures_semaine = int(request.form.get("max_heures_semaine") or enseignant.max_heures_semaine)
        enseignant.disponibilites = request.form.get("disponibilites") or None
        enseignant.indisponibilites = request.form.get("indisponibilites") or None
        db.session.commit()
        flash("Enseignant mis à jour", "success")
        return redirect(url_for("enseignant.detail_enseignant", enseignant_id=enseignant.id))

    sessions = db.session.scalars(
        select(Session).join(Session.enseignants).where(Enseignant.id == enseignant.id)
    ).all()
    return render_template(
        "enseignant/detail.html",
        enseignant=enseignant,
        sessions=sessions,
    )
