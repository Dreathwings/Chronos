# Planificateur d’emplois du temps — Flask + MariaDB

Gestion et optimisation automatisée d’emplois du temps selon:
- disponibilités enseignants  
- capacités et équipements des salles  
- besoins des cours (durée, fenêtres de dates, logiciels, PC)

## Architecture cible
- **API**: Flask + Flask-RESTX (Swagger)
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
DATABASE_URL=mariadb+mariadbconnector://warren@localhost:3306/chrono
DB_ECHO=false
API_TITLE=Chronos API
API_VERSION=0.1.0
ORIGIN=http://localhost:8000
```

## Endpoints principaux
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
