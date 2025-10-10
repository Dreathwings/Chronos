from __future__ import annotations

from datetime import date, time, timedelta

from app import create_app
from app.database import session_scope
from app.models import Base, Enseignant, Matiere, Salle, SessionCours

app = create_app()
engine = app.session_factory().bind  # type: ignore[attr-defined]
assert engine is not None
Base.metadata.create_all(bind=engine)

sample_enseignants = [
    {"nom": "Alice Dupont", "email": "alice.dupont@example.com", "disponibilites": "Lundi au jeudi"},
    {"nom": "Bernard Martin", "email": "bernard.martin@example.com", "disponibilites": "Matin uniquement"},
]

sample_salles = [
    {"nom": "Salle Atlas", "capacite": 40, "equipements": "Vidéoprojecteur, PC"},
    {"nom": "Salle Boreal", "capacite": 25, "equipements": "Tableaux interactifs"},
]

sample_matieres = [
    {
        "nom": "Programmation Python",
        "description": "Initiation et perfectionnement",
        "duree": 120,
        "priorite": 2,
        "besoins": "PC, IDE",
    },
    {
        "nom": "Gestion de projet",
        "description": "Méthodes agiles et outils",
        "duree": 90,
        "priorite": 1,
        "besoins": "Salle modulable",
    },
]

with session_scope(app.session_factory) as session:  # type: ignore[attr-defined]
    session.query(SessionCours).delete()
    session.query(Matiere).delete()
    session.query(Salle).delete()
    session.query(Enseignant).delete()

    enseignants = [Enseignant(**data) for data in sample_enseignants]
    salles = [Salle(**data) for data in sample_salles]
    matieres = [Matiere(**data) for data in sample_matieres]

    session.add_all(enseignants + salles + matieres)
    session.flush()

    today = date.today()
    slots = [
        (today, time(9), time(11)),
        (today + timedelta(days=1), time(14), time(16)),
        (today + timedelta(days=2), time(10), time(12)),
    ]

    for idx, slot in enumerate(slots):
        session.add(
            SessionCours(
                matiere_id=matieres[idx % len(matieres)].id,
                enseignant_id=enseignants[idx % len(enseignants)].id,
                salle_id=salles[idx % len(salles)].id,
                date=slot[0],
                debut=slot[1],
                fin=slot[2],
            )
        )

print("Base de données initialisée avec des données d'exemple.")
