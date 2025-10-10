# Planificateur d’emplois du temps — Flask + MariaDB

Chaque endpoint dispose d'une page HTML qui permet la gestion des elements
Gestion et optimisation automatisée d’emplois du temps selon:
- disponibilités enseignants  
- capacités ,disponibilité et équipements des salles  
- besoins des cours (Taille creneau, fenêtres de dates, logiciels, PC,priorité de placement dans l'emploi du temps)
- Pour chaque pages génére un calendrier contenant tout les cours assigner a cette element

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

> ℹ️  Par défaut l'application utilise SQLite (`DATABASE_URL=sqlite+pysqlite:///chronos.db`).
> Pour MariaDB, remplacez la valeur par `mariadb+pymysql://user:password@host:3306/chronos`.

### Pages HTML incluses

- Tableau de bord `/` avec visualisation globale du calendrier et formulaire rapide de planification.
- Gestion des enseignants `/enseignant` + fiche détaillée `/enseignant/<id>` avec édition inline et calendrier dédié.
- Gestion des salles `/salle` + fiche `/salle/<id>` avec calendrier des réservations.
- Gestion des cours `/matiere` + fiche `/matiere/<id>` pour modifier contraintes et visualiser les séances.

Chaque page liste intègre un formulaire de création, les fiches détaillées permettent l'édition et affichent automatiquement les séances planifiées.

### Données de démonstration

Un script `seed.py` initialise la base avec des enseignants, salles, cours et trois séances réparties sur la semaine courante. Exécutez-le après avoir configuré la base.

## Variables d’environnement (`.env.example`)
```
FLASK_ENV=development
SECRET_KEY=change_me
DATABASE_URL=mariadb+pymysql://warren@localhost:3306/chronos
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

## Génération du code avec Codex
(voir le README complet fourni précédemment)

## Licence
MIT.
