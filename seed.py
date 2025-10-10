from datetime import datetime, timedelta

from app import create_app, db
from app.models import Enseignant, Logiciel, Materiel, Matiere, Salle, Session


def run():
    app = create_app()
    with app.app_context():
        db.create_all()
        if not Enseignant.query.first():
            enseignants = [
                Enseignant(nom="Alice Martin", email="alice@univ.fr", disponibilites="Lun-Jeu 8h-17h"),
                Enseignant(nom="Bruno Lopez", email="bruno@univ.fr", disponibilites="Mar-Ven 9h-18h"),
            ]
            db.session.add_all(enseignants)

        if not Salle.query.first():
            salles = [
                Salle(nom="A101", capacite=35, nombre_pc=20, equipements="Vidéoprojecteur"),
                Salle(nom="Lab Info", capacite=25, nombre_pc=25, equipements="PC, Tableau interactif"),
            ]
            db.session.add_all(salles)

        if not Matiere.query.first():
            matieres = [
                Matiere(nom="Programmation Python", sessions_a_planifier=6, duree_par_session=3, priorite=1),
                Matiere(nom="Gestion de projet", sessions_a_planifier=4, duree_par_session=2, priorite=2),
            ]
            db.session.add_all(matieres)

        if not Logiciel.query.first():
            db.session.add(Logiciel(nom="Python", version="3.11"))
            db.session.add(Logiciel(nom="MS Project", version="2024"))

        if not Materiel.query.first():
            db.session.add(Materiel(nom="Vidéoprojecteur", description="Full HD"))
            db.session.add(Materiel(nom="Tableau interactif"))

        db.session.commit()

        if not Session.query.first():
            python_course = Matiere.query.filter_by(nom="Programmation Python").first()
            salle = Salle.query.filter_by(nom="Lab Info").first()
            enseignant = Enseignant.query.filter_by(nom="Alice Martin").first()
            if python_course and salle and enseignant:
                debut = datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)
                session = Session(
                    matiere=python_course,
                    salle=salle,
                    debut=debut,
                    fin=debut + timedelta(hours=python_course.duree_par_session),
                )
                session.enseignants.append(enseignant)
                db.session.add(session)
                db.session.commit()


if __name__ == "__main__":
    run()
