# Planificateur d’emplois du temps — Flask + MariaDB

Chaque endpoint dispose d'une page HTML qui permet la gestion des elements
Gestion et optimisation automatisée d’emplois du temps selon:
- disponibilités enseignants  
- capacités ,disponibilité et équipements des salles  
- besoins des cours (Taille creneau, fenêtres de dates, logiciels, PC,priorité de placement dans l'emploi du temps)
- Pour chaque pages génére un calendrier contenant tout les cours assigner a cette element

- Tableau de bord `/` avec visualisation globale du calendrier et formulaire rapide de planification.
- Gestion des enseignants `/enseignant` + fiche détaillée `/enseignant/<id>` avec édition inline et calendrier dédié(disponibilité dans les creneaux Horaire, indisponibilité a la journée, nombre d'heure maximum).
- Gestion des salles `/salle` + fiche `/salle/<id>` avec calendrier des réservations(nombre de place, nbr PC, Materiel).
- Gestion des cours `/matiere` + fiche `/matiere/<id>` pour modifier contraintes et visualiser les séances(Besoin en materiel, Logiciel,nombre de seances, nbr creneaux / seance, plages de dates pour le placement automatique du cours, priorité de placement du cours).

Chaque page fiche intègre un formulaire de création, les fiches détaillées permettent l'édition et affichent automatiquement les séances planifiées.
Generer les calendrier avec FullCalendar.js
Plusieur enseignent peuvent être sur le meme cours
Les élement comme [Logiciel,Materiel] sont generer avec une page CRUD et stocké en base de donnée pour standardisé les entrées

## Organisation de Horaire
    Plage Horaire: 8H a 18H en creneau de 1H
        Pause matin: 10H a 10H15
        Pause midi: 1H15 entre 12H et 14H
        Pause aprés-midi: 15H15 a 15H30

## Architecture cible
- **ORM**: SQLAlchemy + Alembic
- **DB**: MariaDB 10.6+
- **Optimisation**: OR-Tools (CP-SAT)
- **Config**: `.env`
- **Conteneurs**: Docker + docker-compose
- **Tests**: pytest

## Démarrage rapide

### Option A — Docker
```bash
cp .env.example .env
docker compose up --build
# Swagger: http://localhost:8000/api/docs
```

### Option B — Local (sans Docker)
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Adapter DATABASE_URL si besoin
alembic upgrade head
python seed.py
flask --app app run --debug --port 8000
```

## Variables d’environnement (`.env.example`)
```
FLASK_ENV=development
SECRET_KEY=change_me
DATABASE_URL=mariadb+mariadbconnector://warren@localhost:3306/chronos
DB_ECHO=false
API_TITLE=Chronos API
API_VERSION=0.1.0
ORIGIN=http://localhost:8000
```

## Pages principals
- `GET /`
- `GET /enseignant` Listing enseignants
- `GET /enseignant/<id>` CRUD enseignant
- `GET /salle` Listing salles
- `GET /salle/<id>` CRUD salles  
- `GET /matiere` Listing cours
- `GET /matiere/<id>` CRUD cours

## Génération du code avec Codex
(voir le README complet fourni précédemment)

## Licence
MIT.
