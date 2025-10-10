# Chronos — Planificateur d'emplois du temps

Application web Flask permettant de piloter la construction d'emplois du temps en centralisant enseignants, salles, cours et ressources pédagogiques. L'interface propose un tableau de bord global avec calendrier FullCalendar et des pages de gestion avec création/édition en ligne.

## Fonctionnalités

- Tableau de bord (`/`) avec statistiques, calendrier global (FullCalendar) et formulaire de planification rapide.
- Gestion des enseignants (`/enseignant`) avec fiche détaillée (`/enseignant/<id>`) affichant les séances assignées et permettant la mise à jour instantanée des informations de disponibilité.
- Gestion des salles (`/salle`) et fiche détaillée (`/salle/<id>`) listant les réservations.
- Gestion des cours (`/matiere`) et fiche (`/matiere/<id>`) pour paramétrer contraintes (durée, priorité, besoins) et ajouter des séances avec affectation des enseignants et des salles.
- Gestion des ressources normalisées : logiciels (`/logiciel`) et matériels (`/materiel`).
- Base de données SQLAlchemy (MariaDB ou SQLite fallback) avec migrations via Flask-Migrate et script de peuplement `seed.py`.

## Prérequis

- Python 3.11+
- MariaDB 10.6+ (ou SQLite pour le développement local rapide)
- Docker / docker-compose (optionnel)

## Installation

### Option A — Docker

```bash
cp .env.example .env
docker compose up --build
# Application disponible sur http://localhost:8000
```

### Option B — Environnement local

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Adapter DATABASE_URL si besoin (SQLite par défaut)
flask --app app db upgrade  # si migrations configurées
python seed.py
flask --app app run --debug --port 8000
```

Le script `seed.py` crée des données d'exemple (enseignants, salles, cours, ressources et une séance planifiée).

## Configuration (`.env`)

Voir `.env.example` pour les variables disponibles :

```
FLASK_ENV=development
SECRET_KEY=change_me
DATABASE_URL=mariadb+mariadbconnector://user:password@localhost:3306/chronos
DB_ECHO=false
API_TITLE=Chronos API
API_VERSION=0.1.0
ORIGIN=http://localhost:8000
```

## Structure des pages

| Page | Description |
|------|-------------|
| `/` | Tableau de bord avec statistiques et calendrier global. |
| `/enseignant` | Liste/Création des enseignants. |
| `/enseignant/<id>` | Edition détaillée, visualisation des séances attribuées. |
| `/salle` | Liste/Création des salles. |
| `/salle/<id>` | Détails et réservations de la salle. |
| `/matiere` | Liste/Création des cours. |
| `/matiere/<id>` | Paramétrage des contraintes et ajout de séances. |
| `/logiciel` | CRUD simple des logiciels pédagogiques. |
| `/materiel` | CRUD simple des matériels. |

## Notes d'architecture

- ORM : SQLAlchemy 2.x avec annotations `Mapped`.
- Migrations : Flask-Migrate (Alembic) — initialisation : `flask --app app db init` puis `flask --app app db migrate`.
- Optimisation : un module `QuickScheduler` prépare le terrain pour l'intégration d'OR-Tools (statistiques et point d'extension pour la planification automatisée).
- Frontend : Bootstrap 5 + FullCalendar via CDN.

## Licence

MIT
