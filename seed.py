from __future__ import annotations

from datetime import date

from app import create_app
from app.database import db
from app.models import Enseignant, Matiere, Salle

app = create_app()


def seed() -> None:
    with app.app_context():
        if Enseignant.query.count() == 0:
            profs = [
                Enseignant(nom="Alice Martin", email="alice.martin@example.com", disponibilites="Lun-Mer 8h-16h"),
                Enseignant(nom="Bruno Caron", email="bruno.caron@example.com", disponibilites="Mar-Jeu 9h-18h"),
            ]
            db.session.add_all(profs)
            db.session.commit()

        if Salle.query.count() == 0:
            rooms = [
                Salle(nom="Amphi 1", capacite=120, equipements="Projecteur, Sonorisation"),
                Salle(nom="Lab Info", capacite=35, equipements="PC, Logiciels scientifiques"),
            ]
            db.session.add_all(rooms)
            db.session.commit()

        if Matiere.query.count() == 0:
            prof_alice = Enseignant.query.filter_by(email="alice.martin@example.com").first()
            prof_bruno = Enseignant.query.filter_by(email="bruno.caron@example.com").first()
            courses = [
                Matiere(
                    nom="Mathématiques avancées",
                    duree=2,
                    capacite_requise=80,
                    besoins="Tableau interactif",
                    logiciels="",
                    priorite=5,
                    fenetre_debut=date.today(),
                    fenetre_fin=date.today(),
                    enseignant=prof_alice,
                ),
                Matiere(
                    nom="Informatique",
                    duree=2,
                    capacite_requise=30,
                    besoins="PC",
                    logiciels="Python, OR-Tools",
                    priorite=4,
                    fenetre_debut=date.today(),
                    fenetre_fin=date.today(),
                    enseignant=prof_bruno,
                ),
            ]
            db.session.add_all(courses)
            db.session.commit()
        print("Base de données initialisée")


if __name__ == "__main__":
    seed()
