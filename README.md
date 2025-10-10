# Planificateur d’emplois du temps — Flask + OR-Tools

Application web permettant de gérer les enseignants, salles et matières puis de générer automatiquement un planning optimisé selon les contraintes décrites dans le cahier des charges.

## Fonctionnalités

- Interfaces HTML complètes pour créer, modifier et supprimer enseignants, salles et matières.
- Visualisation des cours planifiés directement depuis le tableau de bord et depuis les pages de détail de chaque ressource.
- Génération automatique des créneaux avec OR-Tools (CP-SAT) en tenant compte :
  - de la disponibilité des enseignants,
  - des capacités et équipements des salles,
  - de la durée, de la fenêtre de dates et de la priorité des matières.
- Créneaux d’1 heure entre 8h et 18h avec pauses intégrées (10h-10h15, 12h15-13h30, 15h30-15h45).

## Prérequis

- Python 3.11+
- Une base MariaDB ou SQLite (SQLite utilisée par défaut via `DATABASE_URL`)

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python seed.py  # optionnel : ajoute des données de démonstration
flask --app app run --debug --port 8000
```

Les paramètres (clé secrète, URL de base de données, etc.) se configurent via le fichier `.env`.

## Structure des pages

- `/` : tableau de bord et planning généré
- `/enseignant` : listing + création d’enseignants
- `/enseignant/<id>` : édition d’un enseignant et consultation de ses cours
- `/salle` : listing + création de salles
- `/salle/<id>` : édition d’une salle et calendrier associé
- `/matiere` : listing + création de matières
- `/matiere/<id>` : édition d’une matière et créneaux programmés

## Génération du planning

Depuis le tableau de bord, utiliser le bouton « Générer un planning ». Les créneaux existants sont effacés puis recalculés selon les règles d’optimisation. Chaque suppression d’enseignant, salle ou matière retire également les créneaux liés.

## Licence

MIT
