# Planificateur d’emplois du temps — Flask + MariaDB

Chronos est une application Flask qui centralise la gestion des enseignants, des salles, du catalogue de cours et des contraintes matérielles/logicielles pour générer automatiquement (ou manuellement) un emploi du temps optimisé. Chaque ressource dispose de sa fiche détaillée et d’un calendrier interactif construit avec FullCalendar.

- Tableau de bord `/` avec visualisation globale du calendrier et formulaires de planification manuelle et automatique.
- Gestion des enseignants `/enseignant` + fiche détaillée `/enseignant/<id>` avec édition inline, calendrier dédié, disponibilités (créneaux horaires) et indisponibilités à la journée.
- Gestion des salles `/salle` + fiche `/salle/<id>` avec calendrier des réservations (capacité, postes informatiques, matériel associé).
- Gestion des cours `/matiere` + fiche `/matiere/<id>` pour modifier les contraintes et visualiser les séances (matériel, logiciels, nombre de séances, priorité, capacité, besoin informatique).
- Gestion des référentiels `/materiel` et `/logiciel` pour standardiser les ressources utilisées dans les salles et les cours.
- Les calendriers (global + fiches) sont générés avec FullCalendar.js.
- Plusieurs enseignants peuvent intervenir sur un même cours; les contraintes d’équipement, de disponibilité et de capacité sont prises en compte par l’optimiseur.

## Organisation de l’horaire
- Plage horaire : 8h à 18h en créneaux d’1 h.
- Pause matin : 10h00 à 10h15.
- Pause midi : 12h00 à 13h15 (créneaux disponibles à partir de 13h45).
- Pause après-midi : 15h15 à 15h30.

## Architecture
- **Framework** : Flask 3 + application factory (`create_app`).
- **ORM** : SQLAlchemy 2 + Flask-Migrate.
- **DB** : MariaDB 10.6+ (ou SQLite en développement via `DATABASE_URL`).
- **Optimisation** : OR-Tools (CP-SAT) pour l’assignation automatique des séances aux créneaux/ressources.
- **Config** : `.env` + `python-dotenv`.
- **Tests** : pytest (à compléter selon vos besoins).
- **Conteneurs** : Docker + docker-compose (optionnel, cf. instructions ci-dessous).

## Démarrage rapide

### Option A — Docker
```bash
cp .env.example .env
docker compose up --build
# Swagger (à implémenter selon vos besoins) : http://localhost:8000/api/docs
```

### Option B — Local (sans Docker)
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Adapter DATABASE_URL si besoin (SQLite par défaut)
flask --app app db upgrade  # nécessite une migration initiale
python seed.py
flask --app app run --debug --port 8000
```

> ℹ️ Aucun fichier de migration n’est versionné par défaut. Après avoir configuré votre base, générez la migration initiale avec `flask --app app db init` puis `flask --app app db migrate -m "Initial"` avant d’exécuter `flask --app app db upgrade`.

## Fonctionnalités clés
- **Planification automatique** : le formulaire du tableau de bord déclenche `plan_sessions` (OR-Tools) qui affecte les séances restantes des cours aux créneaux disponibles en respectant les contraintes (disponibilités enseignants, capacité et matériel des salles, priorité des cours, etc.).
- **Planification manuelle** : sélectionnez cours / enseignant / salle / créneau pour créer une séance ponctuelle.
- **Calendriers interactifs** : FullCalendar affiche les événements (globaux et par fiche) et consomme l’API JSON (`/api/.../sessions`).
- **Gestion des référentiels** : pages CRUD simples pour alimenter le matériel et les logiciels, utilisés ensuite dans les fiches cours et salles.

## Variables d’environnement (`.env.example`)
```env
FLASK_ENV=development
SECRET_KEY=change_me
DATABASE_URL=sqlite:///chronos.db
DB_ECHO=false
API_TITLE=Chronos API
API_VERSION=0.1.0
ORIGIN=http://localhost:8000
```

## Structure des principaux modèles
- `Teacher`, `TeacherAvailability`, `TeacherUnavailability`
- `Room`, `Material`
- `Course`, `Software`
- `CourseSession` (créneaux planifiés)

## Licence
MIT.
