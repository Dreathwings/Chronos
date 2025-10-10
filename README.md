# Planificateur d’emplois du temps — Flask + MariaDB

Chaque endpoint dispose d'une page HTML qui permet la gestion des elements
Gestion et optimisation automatisée d’emplois du temps selon:
- disponibilités enseignants  
- capacités ,disponibilité et équipements des salles  
- besoins des cours (Taille creneau, fenêtres de dates, logiciels, PC,priorité de placement dans l'emploi du temps)
- Pour chaque pages génére un calendrier contenant tout les cours assigner a cette element

## Architecture
- **Framework web** : Flask 2
- **ORM** : SQLAlchemy 2 + Flask-SQLAlchemy
- **Migrations** : Alembic (via Flask-Migrate)
- **Base de données** : MariaDB 10.6+ (SQLite possible pour le développement)
- **Optimisation** : OR-Tools (CP-SAT)
- **Configuration** : Variables d'environnement via `.env`
- **Interface** : Templates Bootstrap 5

La logique métier est regroupée dans le paquet `app/` :

- `app/models.py` — Modèles SQLAlchemy (enseignants, salles, cours, séances planifiées)
- `app/scheduling.py` — Génération d'emploi du temps avec OR-Tools et contraintes de créneaux
- `app/routes.py` — Routage Flask et écrans HTML (CRUD + calendriers)
- `app/templates/` — Vues HTML pour le tableau de bord et les entités
- `migrations/` — Scripts Alembic pour versionner le schéma

## Démarrage rapide

### Option A — Docker
```bash
cp .env.example .env
docker compose up --build
# Application: http://localhost:8000
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

La commande `seed.py` injecte quelques enseignants, salles et cours de démonstration.

## Variables d’environnement (`.env.example`)
```
FLASK_ENV=development
SECRET_KEY=change_me
DATABASE_URL=mariadb+mariadbconnector://warren@localhost:3306/chrono
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

## Calendrier
    Plage Horaire: 8H a 18H en creneau de 1H
        Pause matin: 10H a 10H15
        Pause midi: 1H15 entre 12H et 14H
        Pause aprés-midi: 15H15 a 15H30

## Licence
MIT.
