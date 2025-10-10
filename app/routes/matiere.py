from __future__ import annotations

from datetime import datetime, timedelta

from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy import select

from .. import db
from ..models import Enseignant, Matiere, Salle, Session

bp = Blueprint("matiere", __name__, url_prefix="/matiere")


@bp.route("", methods=["GET", "POST"])
def list_matieres():
    if request.method == "POST":
        matiere = Matiere(
            nom=request.form.get("nom"),
            description=request.form.get("description") or None,
            sessions_a_planifier=int(request.form.get("sessions_a_planifier") or 1),
            duree_par_session=int(request.form.get("duree_par_session") or 2),
            priorite=int(request.form.get("priorite") or 1),
            besoins_materiel=request.form.get("besoins_materiel") or None,
            besoins_logiciel=request.form.get("besoins_logiciel") or None,
            couleur=request.form.get("couleur") or None,
        )
        db.session.add(matiere)
        db.session.commit()
        flash("Cours créé", "success")
        return redirect(url_for("matiere.list_matieres"))

    matieres = db.session.scalars(select(Matiere).order_by(Matiere.nom)).all()
    return render_template("matiere/list.html", matieres=matieres)


@bp.route("/<int:matiere_id>", methods=["GET", "POST"])
def detail_matiere(matiere_id: int):
    matiere = db.session.get(Matiere, matiere_id)
    if not matiere:
        flash("Cours introuvable", "warning")
        return redirect(url_for("matiere.list_matieres"))

    salles = db.session.scalars(select(Salle).order_by(Salle.nom)).all()
    enseignants = db.session.scalars(select(Enseignant).order_by(Enseignant.nom)).all()

    if request.method == "POST":
        action = request.form.get("action")
        if action == "update":
            matiere.nom = request.form.get("nom") or matiere.nom
            matiere.description = request.form.get("description") or None
            matiere.sessions_a_planifier = int(request.form.get("sessions_a_planifier") or matiere.sessions_a_planifier)
            matiere.duree_par_session = int(request.form.get("duree_par_session") or matiere.duree_par_session)
            matiere.priorite = int(request.form.get("priorite") or matiere.priorite)
            matiere.besoins_materiel = request.form.get("besoins_materiel") or None
            matiere.besoins_logiciel = request.form.get("besoins_logiciel") or None
            matiere.couleur = request.form.get("couleur") or None
            db.session.commit()
            flash("Cours mis à jour", "success")
        elif action == "session":
            debut = datetime.fromisoformat(request.form["debut"])
            duree = int(request.form.get("duree") or matiere.duree_par_session)
            fin = debut + timedelta(hours=duree)
            salle_id = int(request.form.get("salle_id")) if request.form.get("salle_id") else None
            session = Session(matiere=matiere, salle_id=salle_id, debut=debut, fin=fin)
            enseignant_ids = [int(_id) for _id in request.form.getlist("enseignant_ids")]
            if enseignant_ids:
                session.enseignants.extend(
                    db.session.scalars(
                        select(Enseignant).where(Enseignant.id.in_(enseignant_ids))
                    )
                )
            db.session.add(session)
            db.session.commit()
            flash("Séance ajoutée", "success")
        return redirect(url_for("matiere.detail_matiere", matiere_id=matiere.id))

    sessions = db.session.scalars(select(Session).where(Session.matiere_id == matiere.id)).all()
    return render_template(
        "matiere/detail.html",
        matiere=matiere,
        sessions=sessions,
        salles=salles,
        enseignants=enseignants,
    )
