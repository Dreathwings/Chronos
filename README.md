# Chronos — Planificateur d'emplois du temps

Application Flask permettant de gérer enseignants, salles, cours et ressources pour construire un emploi du temps optimisé. Chaque section dispose d'une interface web dédiée avec calendrier FullCalendar pour visualiser les séances programmées.

## Fonctionnalités

- Tableau de bord avec calendrier global et formulaire de planification rapide.
- Gestion des enseignants (créneaux de disponibilité hebdomadaires, jours d'indisponibilité, charge hebdomadaire maximale) et assignation aux cours.
- Gestion des classes (effectifs, indisponibilités ponctuelles) avec association aux cours et calendrier dédié.
- Gestion des salles avec capacités, postes informatiques, matériels et logiciels disponibles.
- Gestion des cours avec contraintes (nombre de séances, durée, période de planification, priorité, équipements et logiciels requis, besoin en ordinateurs) et assignation multi-enseignants.
- Référentiels centralisés pour les matériels et logiciels utilisés lors de la planification.
- Génération automatique de séances respectant les contraintes (créneaux 8h-18h avec pauses définies, disponibilités enseignants et classes, capacités des salles, matériel/logiciel requis).
- Affichage des calendriers individuels (enseignant, classe, salle, cours) via FullCalendar avec grisage automatique des pauses et plages hors planning.
- Édition directe des séances dans les calendriers (glisser-déposer pour déplacer, clic pour supprimer) avec validation serveur des contraintes.

## Prérequis

- Python 3.11+
- MariaDB 10.6+ (optionnel si vous utilisez SQLite pour des tests locaux)

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Créez un fichier `.env` (optionnel) pour définir la clé secrète et l'URL de base de données :

```env
SECRET_KEY=change-me
DATABASE_URL=mysql+pymysql://user:password@localhost:3306/chronos
```

Si `DATABASE_URL` n'est pas défini, l'application utilisera automatiquement une base SQLite `chronos.db` dans le répertoire du projet.

## Lancement

```bash
flask --app app run --debug
```

À la première exécution l'application crée les tables automatiquement. Vous pouvez injecter des données de démonstration :

```bash
flask --app app seed
```

Les principales pages sont accessibles via :

- `/` : tableau de bord et calendrier global
- `/enseignant` : liste des enseignants
- `/enseignant/<id>` : fiche enseignant + calendrier personnel
- `/classe` : liste des classes
- `/classe/<id>` : fiche classe + calendrier dédié
- `/salle` : liste des salles
- `/salle/<id>` : fiche salle + calendrier des réservations
- `/matiere` : liste des cours
- `/matiere/<id>` : fiche cours, contraintes et génération automatique
- `/equipement` : gestion des matériels
- `/logiciel` : gestion des logiciels

## Tests rapides

Pour vérifier que les dépendances Python sont installées correctement :

```bash
python -m compileall app
```

## Notes techniques

- L'algorithme de génération automatique parcourt les jours ouvrés de la plage de dates définie et sélectionne les premiers créneaux disponibles respectant les contraintes (professeur disponible, salle adéquate, ressources requises et charge hebdomadaire maximale).
- Les pauses sont prises en compte avec les créneaux suivants : 08h-09h, 09h-10h, 10h15-11h15, 11h15-12h15, 13h30-14h30, 14h30-15h30, 15h45-16h45, 16h45-17h45.
- Les calendriers sont générés côté client avec FullCalendar (CDN), affichent les journées de 07h à 19h et grisent automatiquement les pauses ainsi que les plages indisponibles (enseignants et classes).

## Licence

MIT
