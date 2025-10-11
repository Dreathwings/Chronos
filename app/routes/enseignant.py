from __future__ import annotations

from flask import (
    Blueprint,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from sqlalchemy import select

from .. import db
from ..models import Enseignant, Session

bp = Blueprint("enseignant", __name__, url_prefix="/enseignant")


def _payload() -> dict:
    data = request.get_json(silent=True)
    if isinstance(data, dict):
        return data
    return request.form.to_dict()


def _to_int(value: object, default: int) -> int:
    try:
        if value is None:
            raise ValueError
        return int(value)
    except (TypeError, ValueError):
        return default


def _clean_text(value: object) -> str | None:
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value or None


def _wants_json_response() -> bool:
    return request.is_json or request.accept_mimetypes.best == "application/json"


@bp.route("", methods=["GET", "POST"])
def list_enseignants():
    if request.method == "POST":
        data = _payload()
        nom = (data.get("nom") or "").strip()
        if not nom:
            if _wants_json_response():
                return jsonify({"error": "Le nom de l'enseignant est requis."}), 400
            flash("Le nom de l'enseignant est requis.", "danger")
            return redirect(url_for("enseignant.list_enseignants"))

        email = _clean_text(data.get("email"))
        disponibilites = _clean_text(data.get("disponibilites"))
        indisponibilites = _clean_text(data.get("indisponibilites"))
        enseignant = Enseignant(
            nom=nom,
            email=email,
            max_heures_semaine=_to_int(data.get("max_heures_semaine"), 20),
            disponibilites=disponibilites,
            indisponibilites=indisponibilites,
        )
        db.session.add(enseignant)
        db.session.commit()
        if _wants_json_response():
            return jsonify({"id": enseignant.id, "nom": enseignant.nom}), 201
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
        data = _payload()

        nom = (data.get("nom") or "").strip()
        if nom:
            enseignant.nom = nom

        enseignant.email = _clean_text(data.get("email"))

        enseignant.max_heures_semaine = _to_int(
            data.get("max_heures_semaine"), enseignant.max_heures_semaine
        )

        for attr in ("disponibilites", "indisponibilites"):
            setattr(enseignant, attr, _clean_text(data.get(attr)))

        db.session.commit()
        if _wants_json_response():
            return jsonify({"status": "updated", "id": enseignant.id})
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
