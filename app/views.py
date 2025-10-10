from __future__ import annotations

from collections import defaultdict
from datetime import date, time
from typing import Iterable

from flask import Blueprint, Flask, flash, redirect, render_template, request, url_for, current_app
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from .database import session_scope
from .models import Base, Enseignant, Matiere, Salle, SessionCours


bp = Blueprint("web", __name__)


def register_blueprints(app: Flask, *, create_schema: bool = True) -> None:
    app.register_blueprint(bp)

    if create_schema:
        # Ensure tables exist when app boots in dev/test context.
        session = app.session_factory()
        engine = session.get_bind()
        assert engine is not None
        Base.metadata.create_all(bind=engine)
        session.close()
        app.session_factory.remove()


@bp.context_processor
def inject_globals():
    return {"app_title": "Chronos"}


@bp.route("/")
def home():
    with session_scope(current_app.session_factory) as session:  # type: ignore[attr-defined]
        sessions = session.execute(
            select(SessionCours)
            .options(joinedload(SessionCours.matiere), joinedload(SessionCours.enseignant), joinedload(SessionCours.salle))
        ).scalars().all()
        calendar = build_calendar_view(sessions)
        enseignants = session.execute(select(Enseignant).order_by(Enseignant.nom)).scalars().all()
        salles = session.execute(select(Salle).order_by(Salle.nom)).scalars().all()
        matieres = session.execute(select(Matiere).order_by(Matiere.nom)).scalars().all()
    return render_template(
        "index.html",
        calendar=calendar,
        enseignants=enseignants,
        salles=salles,
        matieres=matieres,
    )


@bp.route("/enseignant", methods=["GET", "POST"])
def enseignant_list():
    session_factory = current_app.session_factory  # type: ignore[attr-defined]
    if request.method == "POST":
        name = request.form.get("nom", "").strip()
        email = request.form.get("email") or None
        disponibilites = request.form.get("disponibilites") or None
        if not name:
            flash("Le nom de l'enseignant est requis", "error")
        else:
            with session_scope(session_factory) as session:
                enseignant = Enseignant(nom=name, email=email, disponibilites=disponibilites)
                session.add(enseignant)
            flash("Enseignant créé", "success")
            return redirect(url_for("web.enseignant_list"))

    with session_scope(session_factory) as session:
        enseignants = session.execute(select(Enseignant).options(joinedload(Enseignant.cours).joinedload(SessionCours.matiere))).scalars().all()
    return render_template("enseignant_list.html", enseignants=enseignants)


@bp.route("/enseignant/<int:enseignant_id>", methods=["GET", "POST", "DELETE"])
def enseignant_detail(enseignant_id: int):
    session_factory = current_app.session_factory  # type: ignore[attr-defined]

    if request.method == "POST":
        with session_scope(session_factory) as session:
            enseignant = session.get(Enseignant, enseignant_id)
            if not enseignant:
                flash("Enseignant introuvable", "error")
                return redirect(url_for("web.enseignant_list"))
            enseignant.nom = request.form.get("nom", enseignant.nom)
            enseignant.email = request.form.get("email") or None
            enseignant.disponibilites = request.form.get("disponibilites") or None
        flash("Enseignant mis à jour", "success")
        return redirect(url_for("web.enseignant_detail", enseignant_id=enseignant_id))

    with session_scope(session_factory) as session:
        enseignant = session.get(Enseignant, enseignant_id)
        if not enseignant:
            flash("Enseignant introuvable", "error")
            return redirect(url_for("web.enseignant_list"))
        cours = (
            session.execute(
                select(SessionCours)
                .where(SessionCours.enseignant_id == enseignant_id)
                .options(
                    joinedload(SessionCours.matiere),
                    joinedload(SessionCours.salle),
                    joinedload(SessionCours.enseignant),
                )
            )
            .scalars()
            .all()
        )
    calendar = build_calendar_view(cours)
    return render_template("enseignant_detail.html", enseignant=enseignant, cours=cours, calendar=calendar)


@bp.route("/salle", methods=["GET", "POST"])
def salle_list():
    session_factory = current_app.session_factory  # type: ignore[attr-defined]

    if request.method == "POST":
        nom = request.form.get("nom", "").strip()
        capacite = request.form.get("capacite")
        equipements = request.form.get("equipements") or None
        try:
            capacite_value = int(capacite) if capacite else None
        except ValueError:
            flash("La capacité doit être un nombre", "error")
        else:
            if not nom:
                flash("Le nom de la salle est requis", "error")
            else:
                with session_scope(session_factory) as session:
                    salle = Salle(nom=nom, capacite=capacite_value, equipements=equipements)
                    session.add(salle)
                flash("Salle créée", "success")
                return redirect(url_for("web.salle_list"))

    with session_scope(session_factory) as session:
        salles = session.execute(select(Salle).options(joinedload(Salle.cours).joinedload(SessionCours.matiere))).scalars().all()
    return render_template("salle_list.html", salles=salles)


@bp.route("/salle/<int:salle_id>", methods=["GET", "POST"])
def salle_detail(salle_id: int):
    session_factory = current_app.session_factory  # type: ignore[attr-defined]

    if request.method == "POST":
        with session_scope(session_factory) as session:
            salle = session.get(Salle, salle_id)
            if not salle:
                flash("Salle introuvable", "error")
                return redirect(url_for("web.salle_list"))
            salle.nom = request.form.get("nom", salle.nom)
            capacite = request.form.get("capacite")
            try:
                salle.capacite = int(capacite) if capacite else None
            except ValueError:
                flash("La capacité doit être un nombre", "error")
                return redirect(url_for("web.salle_detail", salle_id=salle_id))
            salle.equipements = request.form.get("equipements") or None
        flash("Salle mise à jour", "success")
        return redirect(url_for("web.salle_detail", salle_id=salle_id))

    with session_scope(session_factory) as session:
        salle = session.get(Salle, salle_id)
        if not salle:
            flash("Salle introuvable", "error")
            return redirect(url_for("web.salle_list"))
        cours = (
            session.execute(
                select(SessionCours)
                .where(SessionCours.salle_id == salle_id)
                .options(joinedload(SessionCours.matiere), joinedload(SessionCours.enseignant))
            )
            .scalars()
            .all()
        )
    calendar = build_calendar_view(cours)
    return render_template("salle_detail.html", salle=salle, cours=cours, calendar=calendar)


@bp.route("/matiere", methods=["GET", "POST"])
def matiere_list():
    session_factory = current_app.session_factory  # type: ignore[attr-defined]

    if request.method == "POST":
        nom = request.form.get("nom", "").strip()
        description = request.form.get("description") or None
        duree = request.form.get("duree")
        besoins = request.form.get("besoins") or None
        priorite = request.form.get("priorite")
        fenetre_debut = request.form.get("fenetre_debut") or None
        fenetre_fin = request.form.get("fenetre_fin") or None
        try:
            duree_value = int(duree) if duree else 60
            priorite_value = int(priorite) if priorite else 1
            date_debut = date.fromisoformat(fenetre_debut) if fenetre_debut else None
            date_fin = date.fromisoformat(fenetre_fin) if fenetre_fin else None
        except ValueError:
            flash("Les valeurs numériques ou de date sont invalides", "error")
        else:
            if not nom:
                flash("Le nom du cours est requis", "error")
            else:
                with session_scope(session_factory) as session:
                    matiere = Matiere(
                        nom=nom,
                        description=description,
                        duree=duree_value,
                        besoins=besoins,
                        priorite=priorite_value,
                        fenetre_debut=date_debut,
                        fenetre_fin=date_fin,
                    )
                    session.add(matiere)
                flash("Cours créé", "success")
                return redirect(url_for("web.matiere_list"))

    with session_scope(session_factory) as session:
        matieres = session.execute(select(Matiere).options(joinedload(Matiere.sessions).joinedload(SessionCours.enseignant))).scalars().all()
    return render_template("matiere_list.html", matieres=matieres)


@bp.route("/matiere/<int:matiere_id>", methods=["GET", "POST"])
def matiere_detail(matiere_id: int):
    session_factory = current_app.session_factory  # type: ignore[attr-defined]

    if request.method == "POST":
        with session_scope(session_factory) as session:
            matiere = session.get(Matiere, matiere_id)
            if not matiere:
                flash("Cours introuvable", "error")
                return redirect(url_for("web.matiere_list"))
            matiere.nom = request.form.get("nom", matiere.nom)
            matiere.description = request.form.get("description") or None
            duree = request.form.get("duree")
            priorite = request.form.get("priorite")
            try:
                matiere.duree = int(duree) if duree else matiere.duree
                matiere.priorite = int(priorite) if priorite else matiere.priorite
            except ValueError:
                flash("Les valeurs numériques sont invalides", "error")
                return redirect(url_for("web.matiere_detail", matiere_id=matiere_id))
            besoins = request.form.get("besoins") or None
            fenetre_debut = request.form.get("fenetre_debut") or None
            fenetre_fin = request.form.get("fenetre_fin") or None
            try:
                matiere.fenetre_debut = date.fromisoformat(fenetre_debut) if fenetre_debut else None
                matiere.fenetre_fin = date.fromisoformat(fenetre_fin) if fenetre_fin else None
            except ValueError:
                flash("Format de date invalide", "error")
                return redirect(url_for("web.matiere_detail", matiere_id=matiere_id))
            matiere.besoins = besoins
        flash("Cours mis à jour", "success")
        return redirect(url_for("web.matiere_detail", matiere_id=matiere_id))

    with session_scope(session_factory) as session:
        matiere = session.get(Matiere, matiere_id)
        if not matiere:
            flash("Cours introuvable", "error")
            return redirect(url_for("web.matiere_list"))
        cours = (
            session.execute(
                select(SessionCours)
                .where(SessionCours.matiere_id == matiere_id)
                .options(joinedload(SessionCours.enseignant), joinedload(SessionCours.salle))
            )
            .scalars()
            .all()
        )
    calendar = build_calendar_view(cours)
    return render_template("matiere_detail.html", matiere=matiere, cours=cours, calendar=calendar)


@bp.route("/session", methods=["POST"])
def session_create():
    session_factory = current_app.session_factory  # type: ignore[attr-defined]

    matiere_id = request.form.get("matiere_id")
    enseignant_id = request.form.get("enseignant_id")
    salle_id = request.form.get("salle_id")
    date_raw = request.form.get("date")
    debut_raw = request.form.get("debut")
    fin_raw = request.form.get("fin")

    try:
        matiere_id_val = int(matiere_id) if matiere_id else None
        enseignant_id_val = int(enseignant_id) if enseignant_id else None
        salle_id_val = int(salle_id) if salle_id else None
        session_date = date.fromisoformat(date_raw) if date_raw else None
        start_time = time.fromisoformat(debut_raw) if debut_raw else None
        end_time = time.fromisoformat(fin_raw) if fin_raw else None
    except ValueError:
        flash("Paramètres de session invalides", "error")
        return redirect(request.referrer or url_for("web.home"))

    if not (matiere_id_val and session_date and start_time and end_time):
        flash("Les champs cours, date, début et fin sont obligatoires", "error")
        return redirect(request.referrer or url_for("web.home"))

    with session_scope(session_factory) as session:
        session_cours = SessionCours(
            matiere_id=matiere_id_val,
            enseignant_id=enseignant_id_val,
            salle_id=salle_id_val,
            date=session_date,
            debut=start_time,
            fin=end_time,
        )
        session.add(session_cours)
    flash("Séance créée", "success")
    return redirect(request.referrer or url_for("web.home"))


def build_calendar_view(sessions: Iterable[SessionCours]):
    """Return a nested dict [date][hour] -> list of sessions."""
    calendar: dict[date, dict[str, list[SessionCours]]] = defaultdict(lambda: defaultdict(list))
    for session in sessions:
        key = session.date
        slot_label = f"{session.debut.strftime('%H:%M')} - {session.fin.strftime('%H:%M')}"
        calendar[key][slot_label].append(session)
    ordered = dict(sorted(calendar.items(), key=lambda item: item[0]))
    return {day: dict(sorted(slots.items())) for day, slots in ordered.items()}


__all__ = ["register_blueprints"]
