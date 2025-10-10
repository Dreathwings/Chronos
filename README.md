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
DATABASE_URL=mariadb+mariadbconnector://user:password@localhost:3306/chrono
DB_ECHO=false
API_TITLE=Chronos API
API_VERSION=0.1.0
ORIGIN=http://localhost:8000
```

## Schéma de données (résumé)

- **teachers**: id, name, max_weekly_load_hrs  
- **teacher_availabilities**: id, teacher_id, weekday, start_time, end_time  
- **teacher_unavailabilities**: id, teacher_id, date, start_time, end_time  
- **class_groups**: id, code, name, size, notes
- **rooms**: id, name, capacity, building
- **room_equipment**: id, room_id, key, value  
- **courses**: id, name, group_id, size, teacher_id, sessions_count, session_minutes, window_start, window_end  
- **course_requirements**: id, course_id, key, value  
- **timeslots**: id, date, start_time, end_time, minutes  
- **assignments**: id, course_id, session_index, timeslot_id, room_id, teacher_id, status

## Endpoints principaux

- `POST /api/teachers` CRUD enseignants  
- `POST /api/rooms` CRUD salles  
- `POST /api/courses` CRUD cours  
- `POST /api/timeslots/generate` génère les créneaux potentiels  
- `POST /api/solve` lance l’optimiseur  
- `GET /api/timetable?scope=teacher|group|room&id=...` vue filtrée
- `PATCH /api/assignments/{id}` ajustement manuel
- `GET /api/health` statut

## Interface Web d'administration

En complément de l'API, Chronos fournit une interface HTML responsive accessible sur `http://localhost:8000/`. Elle permet de :

- Visualiser un tableau de bord (effectifs, dernières créations).
- Gérer les **salles** (création, suppression, équipements sous forme `clé=valeur`).
- Gérer les **enseignants** (création, suppression, charge hebdomadaire maximale).
- Gérer les **classes** (code, intitulé, effectif, notes). La suppression est bloquée si des cours sont associés.
- Gérer les **cours** (sélection d'une classe et d'un enseignant, fenêtres de dates, exigences `clé=valeur`).

Les formulaires intègrent des validations basiques et des messages de confirmation/erreur. Les actions reposent sur la même base de données que l'API, ce qui permet d'enchaîner gestion manuelle et appels programmatiques sans désynchronisation.

## Génération du code avec Codex
(voir le README complet fourni précédemment)

## Licence
MIT.
