from __future__ import annotations

from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy import delete

from .database import db
from .models import Creneau, Enseignant, Matiere, Salle
from .scheduler import build_schedule, persist_schedule

bp = Blueprint("chronos", __name__)


def register_routes(app) -> None:
    app.register_blueprint(bp)


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


@bp.route("/")
def index():
    enseignants = Enseignant.query.order_by(Enseignant.nom).all()
    salles = Salle.query.order_by(Salle.nom).all()
    matieres = (
        Matiere.query.order_by(Matiere.priorite.desc(), Matiere.nom).all()
    )
    creneaux = Creneau.query.order_by(Creneau.date, Creneau.debut).all()
    return render_template(
        "index.html",
        enseignants=enseignants,
        salles=salles,
        matieres=matieres,
        creneaux=creneaux,
    )


@bp.post("/schedule")
def schedule():
    matieres = Matiere.query.filter(Matiere.enseignant_id.isnot(None)).all()
    salles = Salle.query.all()
    if matieres and salles:
        db.session.execute(delete(Creneau))
        db.session.commit()
    results = build_schedule(matieres, salles)
    persist_schedule(results)
    if results:
        flash(f"{len(results)} créneaux générés", "success")
    else:
        flash("Aucun créneau généré. Vérifier les données", "warning")
    return redirect(url_for("chronos.index"))


@bp.route("/enseignant", methods=["GET", "POST"])
def enseignants():
    if request.method == "POST":
        enseignant = Enseignant(
            nom=request.form.get("nom", "").strip(),
            email=request.form.get("email", "").strip(),
            disponibilites=request.form.get("disponibilites", ""),
        )
        if not enseignant.nom or not enseignant.email:
            flash("Le nom et l'email sont requis", "danger")
        else:
            db.session.add(enseignant)
            db.session.commit()
            flash("Enseignant créé", "success")
            return redirect(url_for("chronos.enseignants"))
    enseignants = Enseignant.query.order_by(Enseignant.nom).all()
    return render_template("enseignants/list.html", enseignants=enseignants)


@bp.route("/enseignant/<int:enseignant_id>", methods=["GET", "POST"])
def enseignant_detail(enseignant_id: int):
    enseignant = Enseignant.query.get_or_404(enseignant_id)
    if request.method == "POST":
        action = request.form.get("action", "update")
        if action == "delete":
            for matiere in list(enseignant.matieres):
                matiere.enseignant_id = None
            for creneau in list(enseignant.creneaux):
                db.session.delete(creneau)
            db.session.delete(enseignant)
            db.session.commit()
            flash("Enseignant supprimé", "info")
            return redirect(url_for("chronos.enseignants"))
        enseignant.nom = request.form.get("nom", enseignant.nom)
        enseignant.email = request.form.get("email", enseignant.email)
        enseignant.disponibilites = request.form.get(
            "disponibilites", enseignant.disponibilites
        )
        db.session.commit()
        flash("Enseignant mis à jour", "success")
        return redirect(url_for("chronos.enseignant_detail", enseignant_id=enseignant_id))
    return render_template("enseignants/detail.html", enseignant=enseignant)


@bp.route("/salle", methods=["GET", "POST"])
def salles_view():
    if request.method == "POST":
        salle = Salle(
            nom=request.form.get("nom", "").strip(),
            capacite=int(request.form.get("capacite", 0) or 0),
            equipements=request.form.get("equipements", ""),
            disponibilites=request.form.get("disponibilites", ""),
        )
        if not salle.nom or salle.capacite <= 0:
            flash("Nom et capacité positifs requis", "danger")
        else:
            db.session.add(salle)
            db.session.commit()
            flash("Salle créée", "success")
            return redirect(url_for("chronos.salles_view"))
    salles = Salle.query.order_by(Salle.nom).all()
    return render_template("salles/list.html", salles=salles)


@bp.route("/salle/<int:salle_id>", methods=["GET", "POST"])
def salle_detail(salle_id: int):
    salle = Salle.query.get_or_404(salle_id)
    if request.method == "POST":
        action = request.form.get("action", "update")
        if action == "delete":
            for creneau in list(salle.creneaux):
                db.session.delete(creneau)
            db.session.delete(salle)
            db.session.commit()
            flash("Salle supprimée", "info")
            return redirect(url_for("chronos.salles_view"))
        salle.nom = request.form.get("nom", salle.nom)
        salle.capacite = int(request.form.get("capacite", salle.capacite) or salle.capacite)
        salle.equipements = request.form.get("equipements", salle.equipements)
        salle.disponibilites = request.form.get("disponibilites", salle.disponibilites)
        db.session.commit()
        flash("Salle mise à jour", "success")
        return redirect(url_for("chronos.salle_detail", salle_id=salle_id))
    return render_template("salles/detail.html", salle=salle)


@bp.route("/matiere", methods=["GET", "POST"])
def matieres_view():
    enseignants = Enseignant.query.order_by(Enseignant.nom).all()
    salles = Salle.query.order_by(Salle.nom).all()
    if request.method == "POST":
        matiere = Matiere(
            nom=request.form.get("nom", "").strip(),
            duree=int(request.form.get("duree", 1) or 1),
            capacite_requise=int(request.form.get("capacite_requise", 1) or 1),
            fenetre_debut=parse_date(request.form.get("fenetre_debut")),
            fenetre_fin=parse_date(request.form.get("fenetre_fin")),
            besoins=request.form.get("besoins", ""),
            logiciels=request.form.get("logiciels", ""),
            priorite=int(request.form.get("priorite", 1) or 1),
            enseignant_id=int(request.form.get("enseignant_id"))
            if request.form.get("enseignant_id")
            else None,
        )
        if not matiere.nom:
            flash("Le nom du cours est requis", "danger")
        else:
            db.session.add(matiere)
            db.session.commit()
            flash("Matière créée", "success")
            return redirect(url_for("chronos.matieres_view"))
    matieres = (
        Matiere.query.order_by(Matiere.priorite.desc(), Matiere.nom).all()
    )
    return render_template(
        "matieres/list.html",
        matieres=matieres,
        enseignants=enseignants,
        salles=salles,
    )


@bp.route("/matiere/<int:matiere_id>", methods=["GET", "POST"])
def matiere_detail(matiere_id: int):
    matiere = Matiere.query.get_or_404(matiere_id)
    enseignants = Enseignant.query.order_by(Enseignant.nom).all()
    if request.method == "POST":
        action = request.form.get("action", "update")
        if action == "delete":
            for creneau in list(matiere.creneaux):
                db.session.delete(creneau)
            db.session.delete(matiere)
            db.session.commit()
            flash("Matière supprimée", "info")
            return redirect(url_for("chronos.matieres_view"))
        matiere.nom = request.form.get("nom", matiere.nom)
        matiere.duree = int(request.form.get("duree", matiere.duree) or matiere.duree)
        matiere.capacite_requise = int(
            request.form.get("capacite_requise", matiere.capacite_requise)
            or matiere.capacite_requise
        )
        matiere.fenetre_debut = parse_date(request.form.get("fenetre_debut"))
        matiere.fenetre_fin = parse_date(request.form.get("fenetre_fin"))
        matiere.besoins = request.form.get("besoins", matiere.besoins)
        matiere.logiciels = request.form.get("logiciels", matiere.logiciels)
        matiere.priorite = int(request.form.get("priorite", matiere.priorite) or matiere.priorite)
        enseignant_id = request.form.get("enseignant_id")
        matiere.enseignant_id = int(enseignant_id) if enseignant_id else None
        db.session.commit()
        flash("Matière mise à jour", "success")
        return redirect(url_for("chronos.matiere_detail", matiere_id=matiere_id))
    return render_template(
        "matieres/detail.html",
        matiere=matiere,
        enseignants=enseignants,
    )


@bp.route("/creneau/<int:creneau_id>/delete", methods=["POST"])
def delete_creneau(creneau_id: int):
    creneau = Creneau.query.get_or_404(creneau_id)
    db.session.delete(creneau)
    db.session.commit()
    flash("Créneau supprimé", "info")
    return redirect(url_for("chronos.index"))
