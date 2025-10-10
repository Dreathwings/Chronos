from __future__ import annotations

from datetime import datetime, timedelta

from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy import select

from .. import db
from ..models import Enseignant, Matiere, Salle, Session
from ..utils.scheduler import QuickScheduler

bp = Blueprint("dashboard", __name__)


@bp.route("/", methods=["GET", "POST"])
def dashboard():
    enseignants = db.session.scalars(select(Enseignant).order_by(Enseignant.nom)).all()
    salles = db.session.scalars(select(Salle).order_by(Salle.nom)).all()
    matieres = db.session.scalars(select(Matiere).order_by(Matiere.nom)).all()

    if request.method == "POST":
        try:
            matiere_id = int(request.form.get("matiere_id", "0"))
            salle_id = request.form.get("salle_id")
            enseignant_ids = request.form.getlist("enseignant_ids")
            debut = datetime.fromisoformat(request.form["debut"])
            duree = int(request.form.get("duree", "2"))
            fin = debut + timedelta(hours=duree)

            session = Session(
                matiere_id=matiere_id,
                salle_id=int(salle_id) if salle_id else None,
                debut=debut,
                fin=fin,
            )
            if enseignant_ids:
                session.enseignants.extend(
                    db.session.scalars(
                        select(Enseignant).where(Enseignant.id.in_(enseignant_ids))
                    )
                )

            db.session.add(session)
            db.session.commit()
            flash("Séance planifiée avec succès", "success")
            return redirect(url_for("dashboard.dashboard"))
        except Exception as exc:  # pragma: no cover - simple feedback
            db.session.rollback()
            flash(f"Erreur lors de la planification: {exc}", "danger")

    events = [session.as_fullcalendar_event() for session in db.session.scalars(select(Session)).all()]
    stats = QuickScheduler.compute_stats()
    return render_template(
        "dashboard.html",
        enseignants=enseignants,
        salles=salles,
        matieres=matieres,
        events=events,
        stats=stats,
    )
